"""Turn a direct Supabase connection string (db.<ref>.supabase.co, IPv6 only) into Session pooler strings
for the same project on HOST, one per line (the workflow masks them). Reads SUPABASE_DB_URL.

Parsed by hand rather than with urllib, so passwords containing [ ] @ : / # ? still work; the password is
percent-encoded for libpq. If the password is wrapped in square brackets (left over from Supabase's
"[YOUR-PASSWORD]" template), the unwrapped version is tried as well. Never prints the password itself."""
import os
import re
import sys
import urllib.parse as u

raw = os.environ["SUPABASE_DB_URL"].strip()
m = re.match(r"^(postgres(?:ql)?)://(.*)@([^@/]+?)(?::(\d+))?(/[^?]*)?(\?.*)?$", raw)
if not m:
    sys.exit("FAIL  SUPABASE_DB_URL isn't postgresql://user:password@host:port/database")
scheme, cred, host, _port, path, query = m.groups()
user, _, pw = cred.partition(":")
ref = re.match(r"db\.([a-z0-9]+)\.supabase\.co$", host)
if not ref:
    sys.exit("FAIL  SUPABASE_DB_URL host isn't db.<ref>.supabase.co")
pw = u.unquote(pw)
if pw.upper() in ("YOUR-PASSWORD", "[YOUR-PASSWORD]"):
    sys.exit("FAIL  SUPABASE_DB_URL still has the [YOUR-PASSWORD] placeholder; put the database password in")
user = user or "postgres"
if "." not in user:
    user = f"{user}.{ref.group(1)}"
candidates = [pw]
if len(pw) > 2 and pw.startswith("[") and pw.endswith("]"):
    print("note  the password is wrapped in [ ]; trying it with and without the brackets", file=sys.stderr)
    candidates.insert(0, pw[1:-1])
for c in candidates:
    print(f"{scheme}://{u.quote(user, safe='.')}:{u.quote(c, safe='')}@{os.environ['HOST']}:5432{path or '/postgres'}{query or ''}")
