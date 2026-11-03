"""Turn a direct Supabase connection string (db.<ref>.supabase.co, IPv6 only) into the Session pooler
string for the same project on HOST. Prints the URL (the workflow masks it). Reads SUPABASE_DB_URL."""
import os
import re
import urllib.parse as u

p = u.urlsplit(os.environ["SUPABASE_DB_URL"])
ref = re.match(r"db\.([a-z0-9]+)\.supabase\.co$", p.hostname or "").group(1)
user = p.username or "postgres"
if "." not in user:
    user = f"{user}.{ref}"
netloc = f"{user}:{p.password}@{os.environ['HOST']}:5432"
print(u.urlunsplit((p.scheme, netloc, p.path or "/postgres", p.query, "")))
