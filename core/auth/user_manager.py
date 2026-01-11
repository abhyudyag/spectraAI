import os
import json
import hashlib
from datetime import datetime

# Path relative to this file: core/auth/user_manager.py -> ../../data/users.json
USERS_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'users.json'))

class UserManager:
    def __init__(self, users_file=USERS_FILE):
        self.users_file = users_file
        os.makedirs(os.path.dirname(self.users_file), exist_ok=True)
        self._ensure_users_file()

    def _ensure_users_file(self):
        if not os.path.exists(self.users_file):
            # Create default admin user
            default_data = {
                "admin": {
                    "password_hash": self._hash_password("admin"),
                    "created_at": datetime.now().isoformat()
                }
            }
            with open(self.users_file, 'w') as f:
                json.dump(default_data, f, indent=2)

    def _hash_password(self, password):
        # Simple SHA256 hash (in production, use bcrypt/argon2 with salt)
        return hashlib.sha256(password.encode()).hexdigest()

    def authenticate(self, username, password):
        """Returns True if credentials are valid, False otherwise."""
        try:
            with open(self.users_file, 'r') as f:
                users = json.load(f)
            
            user = users.get(username)
            if not user:
                return False
            
            return user['password_hash'] == self._hash_password(password)
        except Exception as e:
            print(f"Authentication error: {e}")
            return False

    def register(self, username, password):
        """Registers a new user. Returns True if successful."""
        try:
            with open(self.users_file, 'r') as f:
                users = json.load(f)
            
            if username in users:
                return False # User already exists
            
            users[username] = {
                "password_hash": self._hash_password(password),
                "created_at": datetime.now().isoformat()
            }
            
            with open(self.users_file, 'w') as f:
                json.dump(users, f, indent=2)
            return True
        except Exception as e:
            print(f"Registration error: {e}")
            return False

    def get_user_session_dir(self, username):
        """Returns the specific session directory for a user."""
        # ../../data/sessions/{username}
        base_data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data'))
        return os.path.join(base_data_dir, 'sessions', username)
