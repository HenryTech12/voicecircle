"""Write the OpenAPI schema to api/openapi.json (used by `npm run gen:types` in web/)."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app.main import app  # noqa: E402

out = pathlib.Path(__file__).resolve().parents[1] / "openapi.json"
out.write_text(json.dumps(app.openapi(), indent=2))
print(f"wrote {out}")
