import os
import json
from typing import List, Dict, Optional
from datetime import datetime

DEFAULT_SESSION_TITLE = "New Chat"


class ChatHistoryStore:
    def __init__(self, history_dir: str):
        self.history_dir = history_dir
        os.makedirs(history_dir, exist_ok=True)
    
    def _sanitize_filename(self, text: str, max_length: int = 40) -> str:
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in text)
        safe = safe.replace(" ", "_")
        while "__" in safe:
            safe = safe.replace("__", "_")
        return safe[:max_length].strip("_")
    
    def _get_session_path(self, session_id: str, title: str = None) -> str:
        short_id = session_id[-8:] if len(session_id) > 8 else session_id
        
        if title and title != DEFAULT_SESSION_TITLE:
            safe_title = self._sanitize_filename(title)
            filename = f"{safe_title}_{short_id}.json"
        else:
            filename = f"chat_{short_id}.json"
        
        return os.path.join(self.history_dir, filename)
    
    def _find_existing_file(self, session_id: str) -> Optional[str]:
        if not os.path.exists(self.history_dir):
            return None
        
        for filename in os.listdir(self.history_dir):
            if not filename.endswith(".json"):
                continue
            
            path = os.path.join(self.history_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("session_id") == session_id:
                        return path
            except:
                continue
        
        return None
    
    def save_messages(
        self,
        session_id: str,
        messages: List[Dict],
        title: str = None,
        timestamp: int = None,
        owner_key: str = None
    ) -> None:
        if not session_id:
            return
        
        old_path = self._find_existing_file(session_id)
        
        existing_data = {}
        if old_path and os.path.exists(old_path):
            try:
                with open(old_path, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
            except:
                pass
        
        final_title = title or existing_data.get("title", DEFAULT_SESSION_TITLE)
        final_timestamp = timestamp or existing_data.get("timestamp", int(datetime.now().timestamp() * 1000))
        
        data = {
            "session_id": session_id,
            "title": final_title,
            "timestamp": final_timestamp,
            "last_updated": datetime.now().isoformat(),
            "messages": messages
        }
        if owner_key:
            data["owner_key"] = owner_key
        
        new_path = self._get_session_path(session_id, final_title)
        
        if old_path and old_path != new_path and os.path.exists(old_path):
            try:
                os.remove(old_path)
            except:
                pass
        
        with open(new_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def load_messages(self, session_id: str) -> List[Dict]:
        if not session_id:
            return []
        
        path = self._find_existing_file(session_id)
        if not path or not os.path.exists(path):
            return []
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("messages", [])
        except (json.JSONDecodeError, IOError):
            return []
    
    def delete_session(self, session_id: str) -> bool:
        if not session_id:
            return False
        
        path = self._find_existing_file(session_id)
        if path and os.path.exists(path):
            try:
                os.remove(path)
                return True
            except OSError:
                return False
        return False
    
    def list_sessions(self, owner_key: str = None) -> List[Dict]:
        sessions = []
        
        if not os.path.exists(self.history_dir):
            return sessions
        
        for filename in os.listdir(self.history_dir):
            if not filename.endswith(".json"):
                continue
            
            path = os.path.join(self.history_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if owner_key and data.get("owner_key") != owner_key:
                        continue
                    sessions.append({
                        "id": data.get("session_id", ""),
                        "title": data.get("title", DEFAULT_SESSION_TITLE),
                        "ts": data.get("timestamp", 0),
                        "message_count": len(data.get("messages", []))
                    })
            except (json.JSONDecodeError, IOError):
                continue
        
        sessions.sort(key=lambda x: x.get("ts", 0), reverse=True)
        return sessions
