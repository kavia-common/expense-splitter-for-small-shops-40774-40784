import json
import os
from app import app, api  # import your Flask app and Api instance

# PUBLIC_INTERFACE
def generate_and_write_openapi_spec(output_dir: str = "interfaces", filename: str = "openapi.json") -> str:
    """Generate OpenAPI specification from flask-smorest Api and write it to disk.

    Returns:
        str: The absolute path of the written openapi.json file.
    """
    with app.app_context():
        # flask-smorest stores the spec in api.spec
        openapi_spec = api.spec.to_dict()

        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, filename)

        with open(output_path, "w") as f:
            json.dump(openapi_spec, f, indent=2)

        return os.path.abspath(output_path)


if __name__ == "__main__":
    # Allow running this script directly
    out_path = generate_and_write_openapi_spec()
    print(f"OpenAPI spec written to: {out_path}")
