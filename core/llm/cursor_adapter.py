import subprocess
import json
import re
from types import SimpleNamespace
import threading
import queue

class CursorLLM:
    """
    A stateful adapter that uses `create-chat` and `resume`
    to hold a persistent conversation with the Cursor Agent CLI.
    This version uses a robust stream reader to handle large JSON payloads.
    """
    def __init__(self):
        self.chat_id = self._create_chat_session()
        if not self.chat_id:
            raise ConnectionError("Failed to create a chat session with Cursor Agent. Please ensure 'cursor-agent' is installed and you have logged in.")

    def _create_chat_session(self):
        """Starts a new chat and returns the session ID."""
        print("🤖--> Creating new Cursor Agent chat session...")
        try:
            result = subprocess.run(
                ["cursor-agent", "create-chat"],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
                encoding='utf-8'
            )
            chat_id = result.stdout.strip()
            if chat_id:
                print(f"✅ Chat session created with ID: {chat_id}")
                return chat_id
            else:
                print(f"🚨 Failed to create chat session. Output: {result.stdout}")
                return None
        except FileNotFoundError:
            print("🚨 FATAL: 'cursor-agent' command not found. Please install it and ensure it's in your PATH.")
            return None
        except Exception as e:
            print(f"🚨 Error creating chat session: {e}")
            return None

    def _read_stream(self, stream, queue):
        """Reads a stream until EOF and puts the result in a queue."""
        try:
            output = stream.read()
            queue.put(output)
        except Exception as e:
            queue.put(f"Error reading stream: {e}")
        finally:
            stream.close()

    def generate_content(self, prompt_text: str):
        """Sends a prompt to the existing chat session."""
        if not self.chat_id:
            error_message = "No active chat session."
            return SimpleNamespace(text=json.dumps({"error": error_message}))

        print(f"🤖--> Sending prompt to Cursor Agent (session: {self.chat_id[:8]}...)")

        command = [
            "cursor-agent",
            "--print",
            "--output-format", "stream-json",
            "--resume", self.chat_id,
            "--",
            prompt_text
        ]
        
        proc = None
        try:
            print(f"Executing command: {' '.join(command[:6])} [prompt...]")
            
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding='utf-8',
                bufsize=-1 # Use system default buffering (usually large)
            )

            # Use threads to read stdout and stderr concurrently
            # This prevents deadlocks if one buffer fills up
            stdout_q = queue.Queue()
            stderr_q = queue.Queue()
            
            t_out = threading.Thread(target=self._read_stream, args=(proc.stdout, stdout_q))
            t_err = threading.Thread(target=self._read_stream, args=(proc.stderr, stderr_q))
            
            t_out.start()
            t_err.start()

            # Wait for the process to finish (with a generous timeout for large tasks)
            proc.wait(timeout=300) # 5 minutes

            t_out.join()
            t_err.join()
            
            stdout_data = stdout_q.get()
            stderr_data = stderr_q.get()

            if proc.returncode != 0:
                print(f"🚨 Command failed with return code {proc.returncode}")
                print(f"Stderr: {stderr_data}")
                return SimpleNamespace(text="")

            # Process the stream to find the final response
            accumulated_text = ""
            for line in stdout_data.strip().split('\n'):
                try:
                    data = json.loads(line)
                    if data.get("type") == "assistant":
                        if "content" in data.get("message", {}) and data["message"]["content"]:
                            text_chunk = data["message"]["content"][0].get("text", "")
                            accumulated_text += text_chunk
                except (json.JSONDecodeError, KeyError):
                    continue

            print(f"✅ Received response: {len(accumulated_text)} characters")
            return SimpleNamespace(text=accumulated_text)

        except subprocess.TimeoutExpired:
            print(f"🚨 Command timed out after 300 seconds. Terminating process.")
            if proc:
                proc.kill()
            return SimpleNamespace(text="")
        except Exception as e:
            print(f"🚨 An unexpected error occurred: {e}")
            if proc:
                proc.kill()
            return SimpleNamespace(text="")