import os
import json
import glob
from datetime import datetime

class SessionManager:
    def __init__(self, username="default"):
        # Calculate session dir based on username: data/sessions/{username}
        base_session_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'sessions'))
        self.session_dir = os.path.join(base_session_dir, username)
        os.makedirs(self.session_dir, exist_ok=True)

    def list_sessions(self):
        """Returns a list of dicts with session metadata."""
        sessions = []
        files = glob.glob(os.path.join(self.session_dir, "*.json"))
        # Sort by modification time, newest first
        files.sort(key=os.path.getmtime, reverse=True)
        
        for f in files:
            try:
                with open(f, 'r') as file:
                    data = json.load(file)
                    # Basic validation/metadata extraction
                    sessions.append({
                        "id": data.get("session_id"),
                        "filename": os.path.basename(f),
                        "name": data.get("session_name", os.path.basename(f).replace(".json", "")), # User-friendly name
                        "timestamp": data.get("timestamp"),
                        "preview": self._get_preview(data),
                        "agent": data.get("agent_name", "Unknown"),
                        "mode": data.get("agent_mode", "Unknown")
                    })
            except Exception:
                continue
        return sessions

    def _get_preview(self, data):
        """Extracts a short preview string from the conversation history."""
        # Check 'session_data' first (structure from save_session)
        session_data = data.get("session_data", {})
        history = session_data.get("conversation_history", [])
        
        # If flat structure (legacy compatibility)
        if not history and "conversation_history" in data:
            history = data["conversation_history"]
            
        if history:
            # Get the last user message or assistant message
            last_msg = history[-1].get("content", "")
            # Truncate
            return (last_msg[:60] + '...') if len(last_msg) > 60 else last_msg
        return "New Session"

    def save_session(self, session_id, session_data, agent_state, agent_name, agent_mode, db_path, collection_name, session_name=None, profile_config=None, profile_name=None):
        """Saves the current session state to a JSON file."""
        
        # If a friendly name is provided, use it for the filename (sanitized), otherwise use session_id
        if session_name:
            # Simple sanitization
            safe_name = "".join([c for c in session_name if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()
            filename = f"{safe_name}.json"
        else:
            filename = f"{session_id}.json"
            
        filepath = os.path.join(self.session_dir, filename)
        
        save_data = {
            "session_id": session_id,
            "session_name": session_name or session_id,
            "timestamp": datetime.now().isoformat(),
            "agent_name": agent_name,
            "agent_mode": agent_mode,
            "agent_state": agent_state,
            "db_path": db_path,
            "collection_name": collection_name,
            "profile_config": profile_config or {},
            "profile_name": profile_name or "Unknown",
            "session_data": session_data
        }
        
        try:
            with open(filepath, 'w') as f:
                json.dump(save_data, f, indent=2)
            return filepath
        except Exception as e:
            print(f"Error saving session: {e}")
            return None

    def load_session(self, session_id_or_filename):
        """Loads a session from disk."""
        if not session_id_or_filename.endswith(".json"):
            filename = f"{session_id_or_filename}.json"
        else:
            filename = session_id_or_filename
            
        filepath = os.path.join(self.session_dir, filename)
        if not os.path.exists(filepath):
            return None
            
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading session: {e}")
            return None

    def delete_session(self, session_id_or_filename):
         if not session_id_or_filename.endswith(".json"):
            filename = f"{session_id_or_filename}.json"
         else:
            filename = session_id_or_filename
            
         filepath = os.path.join(self.session_dir, filename)
         if os.path.exists(filepath):
             os.remove(filepath)
             return True
         return False

