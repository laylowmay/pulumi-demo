"""
Animal Gallery — GCP + Pulumi demo.

Reads the ``animal`` config key, downloads a photo of that animal from
loremflickr.com, stores it in a Google Cloud Storage bucket, then deploys
a Cloud Run v2 service that renders a simple HTML page showing the image.

Required stack config
---------------------
animal       (string) – name of the animal, e.g. "cat", "elephant", "fox"
gcp:project  (string) – GCP project ID

Optional stack config
---------------------
gcp:region   (string) – GCP region, defaults to "us-central1"
"""

import base64

import pulumi
import pulumi_gcp as gcp

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
config = pulumi.Config()
animal: str = config.require("animal")

gcp_config = pulumi.Config("gcp")
region: str = gcp_config.get("region") or "us-central1"

# ---------------------------------------------------------------------------
# Enable the Cloud Run API for this project
# ---------------------------------------------------------------------------
cloud_run_api = gcp.projects.Service(
    "cloud-run-api",
    service="run.googleapis.com",
    disable_on_destroy=False,
)

# ---------------------------------------------------------------------------
# GCS bucket — stores the downloaded animal image
# ---------------------------------------------------------------------------
bucket = gcp.storage.Bucket(
    "animal-images-bucket",
    location="US",
    # Uniform IAM is required when making objects public via BucketIAMBinding
    uniform_bucket_level_access=True,
    # Allow `pulumi destroy` to remove a non-empty bucket
    force_destroy=True,
)

# Grant public read on every object so the browser can load the image URL
gcp.storage.BucketIAMBinding(
    "bucket-public-binding",
    bucket=bucket.name,
    role="roles/storage.objectViewer",
    members=["allUsers"],
)

# ---------------------------------------------------------------------------
# Download animal image and upload it to GCS
# ---------------------------------------------------------------------------
# pulumi.RemoteAsset fetches the URL at deploy time and uploads the bytes.
# loremflickr.com returns a real JPEG from Flickr for any keyword (follows
# HTTP redirects automatically).
image_object = gcp.storage.BucketObject(
    "animal-image",
    bucket=bucket.name,
    name=f"{animal}.jpg",
    source=pulumi.RemoteAsset(f"https://loremflickr.com/800/600/{animal}"),
    content_type="image/jpeg",
)

# HTTPS URL used in the Cloud Run page's <img src="...">
image_url: pulumi.Output[str] = pulumi.Output.all(
    bucket.name, image_object.output_name
).apply(lambda args: f"https://storage.googleapis.com/{args[0]}/{args[1]}")

# ---------------------------------------------------------------------------
# Inline Python HTTP server
# ---------------------------------------------------------------------------
# This tiny stdlib server runs inside the stock python:3.11-slim Docker image
# — no custom Dockerfile, no registry push required.  It is base64-encoded so
# it can be safely embedded as an environment variable (no shell-escaping
# concerns).  The container bootstrap command is:
#   python3 -c "import base64,os; exec(base64.b64decode(os.environ['SCRIPT']).decode())"
_SERVER_SCRIPT = """\
import os
import http.server

IMAGE_URL = os.environ.get("IMAGE_URL", "")
ANIMAL = os.environ.get("ANIMAL", "animal").capitalize()


def build_page(animal: str, image_url: str) -> str:
    \"\"\"Return a self-contained HTML page that displays the animal photo.\"\"\"
    return (
        "<!DOCTYPE html>"
        "<html lang='en'>"
        "<head>"
        "  <meta charset='utf-8'/>"
        "  <meta name='viewport' content='width=device-width,initial-scale=1'/>"
        "  <title>" + animal + " Gallery</title>"
        "  <style>"
        "    * { box-sizing: border-box; margin: 0; padding: 0; }"
        "    body {"
        "      display: flex; flex-direction: column; align-items: center;"
        "      justify-content: center; min-height: 100vh; gap: 32px;"
        "      background: #0f0f1a; color: #e8e8f0;"
        "      font-family: 'Segoe UI', Arial, sans-serif; padding: 24px;"
        "    }"
        "    h1 {"
        "      font-size: clamp(1.8rem, 5vw, 3rem);"
        "      text-transform: capitalize; letter-spacing: .04em;"
        "    }"
        "    img {"
        "      max-width: min(800px, 100%); border-radius: 18px;"
        "      box-shadow: 0 12px 48px rgba(0,0,0,.7);"
        "    }"
        "    footer { font-size: .8rem; opacity: .45; }"
        "  </style>"
        "</head>"
        "<body>"
        "  <h1>" + animal + "</h1>"
        "  <img src='" + image_url + "' alt='" + animal + "'/>"
        "  <footer>Powered by Google Cloud Storage &amp; Cloud Run &mdash; Pulumi</footer>"
        "</body>"
        "</html>"
    )


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = build_page(ANIMAL, IMAGE_URL).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        pass  # suppress per-request stdout noise


http.server.HTTPServer(("", 8080), _Handler).serve_forever()
"""

_SCRIPT_B64: str = base64.b64encode(_SERVER_SCRIPT.encode()).decode()

# ---------------------------------------------------------------------------
# Cloud Run v2 service — serves the animal gallery page
# ---------------------------------------------------------------------------
cloud_run = gcp.cloudrunv2.Service(
    "animal-viewer",
    location=region,
    # Allow traffic from the public internet
    ingress="INGRESS_TRAFFIC_ALL",
    # Allow `pulumi destroy` to tear the service down
    deletion_protection=False,
    template=gcp.cloudrunv2.ServiceTemplateArgs(
        containers=[
            gcp.cloudrunv2.ServiceTemplateContainerArgs(
                # Public Python image from Docker Hub — no custom build needed
                image="python:3.11-slim",
                # Override the entrypoint so the container decodes and runs
                # the SCRIPT env var using only the standard library
                commands=["python3", "-c"],
                args=[
                    "import base64,os; exec(base64.b64decode(os.environ['SCRIPT']).decode())"
                ],
                envs=[
                    # The base64-encoded server script
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="SCRIPT",
                        value=_SCRIPT_B64,
                    ),
                    # Public GCS URL of the animal image (resolved at deploy time)
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="IMAGE_URL",
                        value=image_url,
                    ),
                    # Animal name, passed through for the page title / heading
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="ANIMAL",
                        value=animal,
                    ),
                ],
                ports=gcp.cloudrunv2.ServiceTemplateContainerPortsArgs(
                    container_port=8080,
                ),
                resources=gcp.cloudrunv2.ServiceTemplateContainerResourcesArgs(
                    limits={"cpu": "1", "memory": "256Mi"},
                ),
            )
        ],
    ),
    opts=pulumi.ResourceOptions(depends_on=[cloud_run_api]),
)

# Allow unauthenticated (public) invocation of the Cloud Run service
gcp.cloudrunv2.ServiceIamMember(
    "all-users-invoker",
    name=cloud_run.name,
    location=region,
    role="roles/run.invoker",
    member="allUsers",
)

# ---------------------------------------------------------------------------
# Stack outputs
# ---------------------------------------------------------------------------
pulumi.export("website_url", cloud_run.uri)
pulumi.export("image_gcs_url", image_url)
pulumi.export("bucket_name", bucket.name)
