import regex as re
from tree_sitter_languages import get_parser, get_language

def _chunk_cobol_file(file_path, file_content):
    """
    A specialized chunker for COBOL (.cbl, .cob) and Pro*COBOL (.pco) files.
    It splits primarily by DIVISIONs, and attempts to find SECTIONS or PARAGRAPHS
    within the PROCEDURE DIVISION if it's too large.
    """
    chunks = []
    
    # Common COBOL Divisions
    division_pattern = re.compile(
        r'^\s{0,7}(IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\.',
        re.MULTILINE | re.IGNORECASE
    )
    
    # Find all division starts
    matches = list(division_pattern.finditer(file_content))
    
    if not matches:
        # Fallback: maybe it's just a copybook or fragment. Split by paragraph-like structure
        return [{"text_chunk": file_content, "metadata": {"file_path": file_path, "type": "cobol_fragment"}}]

    last_pos = 0
    last_type = "preamble"
    
    for i, match in enumerate(matches):
        start = match.start()
        
        # Capture text before this match as the previous chunk
        if start > last_pos:
            chunk_text = file_content[last_pos:start].strip()
            if chunk_text:
                chunks.append({
                    "text_chunk": chunk_text,
                    "metadata": {"file_path": file_path, "type": last_type}
                })
        
        last_pos = start
        last_type = f"{match.group(1).lower()}_division"

    # Add the final chunk (usually Procedure Division)
    if last_pos < len(file_content):
        final_chunk_text = file_content[last_pos:].strip()
        if final_chunk_text:
            # If it's the Procedure Division, we might want to split it further into Sections/Paragraphs
            if "procedure" in last_type:
                # Regex for Sections: "MAIN-LOGIC SECTION."
                section_pattern = re.compile(r'^\s{0,7}([\w-]+)\s+SECTION\.', re.MULTILINE | re.IGNORECASE)
                sec_matches = list(section_pattern.finditer(final_chunk_text))
                
                if sec_matches:
                    sec_last_pos = 0
                    for sm in sec_matches:
                        s_start = sm.start()
                        if s_start > sec_last_pos:
                            s_text = final_chunk_text[sec_last_pos:s_start].strip()
                            if s_text:
                                chunks.append({
                                    "text_chunk": s_text,
                                    "metadata": {"file_path": file_path, "type": "procedure_code"}
                                })
                        sec_last_pos = s_start
                    
                    # Last section
                    chunks.append({
                        "text_chunk": final_chunk_text[sec_last_pos:].strip(),
                        "metadata": {"file_path": file_path, "type": "procedure_section"}
                    })
                else:
                    chunks.append({
                        "text_chunk": final_chunk_text,
                        "metadata": {"file_path": file_path, "type": last_type}
                    })
            else:
                chunks.append({
                    "text_chunk": final_chunk_text,
                    "metadata": {"file_path": file_path, "type": last_type}
                })

    return chunks

def _chunk_proc_file(file_path, file_content):
    """
    A specialized chunker for Pro*C (.pc) files using regular expressions.
    It identifies both C functions and embedded EXEC SQL blocks.
    """
    chunks = []
    # This regex uses a lookahead to handle nested braces in C functions
    # and also captures EXEC SQL blocks.
    pattern = re.compile(
        r'(EXEC SQL.*?;)|'  # Group 1: Matches EXEC SQL statements
        r'(\w+\s+\**\s*\w+\s*\([^)]*\)\s*\{(?:[^{}]|(?R))*\})',  # Group 2: Matches C functions with bodies
        re.DOTALL | re.IGNORECASE
    )
    
    last_end = 0
    for match in pattern.finditer(file_content):
        start, end = match.span()
        
        # Capture any code that exists *between* matched chunks (like global variables)
        if start > last_end:
            interim_text = file_content[last_end:start].strip()
            if interim_text:
                chunks.append({
                    "text_chunk": interim_text,
                    "metadata": {"file_path": file_path, "type": "global_code"}
                })
        
        # Determine the type of chunk we found
        chunk_text = match.group(0)
        chunk_type = "sql_block" if match.group(1) else "c_function"
        
        chunks.append({
            "text_chunk": chunk_text,
            "metadata": {"file_path": file_path, "type": chunk_type}
        })
        last_end = end

    # Capture any remaining code at the end of the file
    if last_end < len(file_content):
        remaining_text = file_content[last_end:].strip()
        if remaining_text:
            chunks.append({
                "text_chunk": remaining_text,
                "metadata": {"file_path": file_path, "type": "global_code"}
            })

    # If no regex matches were found at all, just add the whole file.
    if not chunks and file_content.strip():
        chunks.append({"text_chunk": file_content, "metadata": {"file_path": file_path, "type": "file"}})
        
    return chunks

def chunk_code_by_functions(file_path, file_content, language="java"):
    """
    Acts as a dispatcher, choosing the correct chunking strategy based on language.
    """
    if language in ["java", "python", "c"]:
        try:
            lang = get_language(language)
            parser = get_parser(language)
            tree = parser.parse(bytes(file_content, "utf8"))
            queries = {
                "c": "(function_definition) @func (struct_specifier) @struct (enum_specifier) @enum",
                "java": "(method_declaration) @func (class_declaration) @class (interface_declaration) @interface (constructor_declaration) @func",
                "python": "(function_definition) @func (class_definition) @class"
            }
            query_string = queries.get(language, "")
            if not query_string:
                raise Exception(f"No query defined for language: {language}")
                
            query = lang.query(query_string)
            captures = query.captures(tree.root_node)
            
            if not captures: # If no functions found, treat as one chunk
                return [{"text_chunk": file_content, "metadata": {"file_path": file_path, "type": "file"}}]

            # Add metadata including line numbers for better context
            return [{
                "text_chunk": node.text.decode('utf8'),
                "metadata": {
                    "file_path": file_path, 
                    "type": name, 
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1
                }
            } for node, name in captures]

        except Exception as e:
            print(f"Tree-sitter failed for {file_path}: {e}. Falling back to whole file chunking.")
            return [{"text_chunk": file_content, "metadata": {"file_path": file_path, "type": "file"}}]

    elif language == "proc":
        return _chunk_proc_file(file_path, file_content)

    elif language == "cobol":
        return _chunk_cobol_file(file_path, file_content)

    # Treat shell scripts and plain documents similarly by splitting by paragraph
    elif language == "document" or language == "shell":
        chunks = []
        content_chunks = file_content.split("\n\n") # Split by paragraph
        for i, text_chunk in enumerate(content_chunks):
            if text_chunk.strip():
                chunks.append({
                    "text_chunk": text_chunk, 
                    "metadata": {"file_path": file_path, "type": "paragraph", "block": i}
                })
        
        if not chunks and file_content.strip():
             return [{"text_chunk": file_content, "metadata": {"file_path": file_path, "type": "file"}}]
        return chunks
    
    # Default fallback for any other unknown languages
    return [{"text_chunk": file_content, "metadata": {"file_path": file_path, "type": "file"}}]
