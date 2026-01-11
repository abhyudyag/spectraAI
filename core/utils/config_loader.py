import os
import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
PROFILES_DIR = os.path.join(PROJECT_ROOT, 'config', 'profiles')

def list_profiles():
    """
    Scans config/profiles/ for .yaml files and returns a list of profile names
    (filenames without extension).
    """
    if not os.path.exists(PROFILES_DIR):
        return []
    
    profiles = []
    for f in os.listdir(PROFILES_DIR):
        if f.endswith('.yaml') or f.endswith('.yml'):
            profiles.append(os.path.splitext(f)[0])
    return profiles

def load_profile(profile_name):
    """
    Loads a specific profile configuration by name.
    """
    # Try both extensions
    for ext in ['.yaml', '.yml']:
        path = os.path.join(PROFILES_DIR, f"{profile_name}{ext}")
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    return yaml.safe_load(f)
            except Exception as e:
                print(f"🚨 Error loading profile {profile_name}: {e}")
                return None
    
    print(f"🚨 Profile not found: {profile_name}")
    return None
