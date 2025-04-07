import argparse
import os
import json
import shutil
import datetime
import subprocess
from pathlib import Path
import dotenv
import sys
from azure.storage.blob import BlobServiceClient, ContainerClient


def symbol_name(app_name):
    return app_name.lower().replace(" ", "").replace("_", "").replace("-", "")


def download_blob(
    blob_container_client: ContainerClient, blob_name: str, download_path: str
):
    print(f"Starting download of {blob_name}...")
    blob_name_parts = blob_name.split("/")
    blob_file_name = blob_name_parts[-1]

    # Download with progress tracking
    with open(os.path.join(download_path, blob_file_name), "wb") as download_file:
        download_stream = blob_container_client.download_blob(blob_name)
        total_size = download_stream.properties.size
        bytes_downloaded = 0

        for chunk in download_stream.chunks():
            download_file.write(chunk)
            bytes_downloaded += len(chunk)

            # Update progress
            if total_size > 0:
                percent = int(100 * bytes_downloaded / total_size)
                print(
                    f"\rDownload progress: {percent}% ({bytes_downloaded/1024:.1f}KB / {total_size/1024:.1f}KB)",
                    end="",
                )

    print()  # New line after download completes


def get_symbols(application_major, app_dependencies: dict):
    """Collect and download symbols and dependencies"""
    # Create the download destination
    DownloadPathDestination = os.path.join(os.getcwd(), "symbols")
    if not os.path.exists(DownloadPathDestination):
        os.mkdir(DownloadPathDestination)

    # Azure Blob Storage settings
    connection_string = os.getenv("AZ_CONNECTION_STRING")
    container_name_ms_symbols = os.getenv("AZ_CONTAINER_NAME_MSSYMBOLS")
    container_name_dependencies = os.getenv("AZ_CONTAINER_NAME_DEPENDENCIES")

    blob_service_client = BlobServiceClient.from_connection_string(connection_string)

    # Microsoft symbols
    print(f"Downloading MS Symbols from Azure Storage - Version {application_major}...")
    blob_container_client = blob_service_client.get_container_client(
        container_name_ms_symbols
    )
    blob_names = blob_container_client.list_blobs(f"{application_major}")
    for blob in blob_names:
        print(f"Downloading {blob.name}...")
        download_blob(blob_container_client, blob.name, DownloadPathDestination)

    # Dependencies symbols
    print("Downloading Other Symbols from Azure Storage...")

    blob_container_client = blob_service_client.get_container_client(
        container_name_dependencies
    )
    blob_names = blob_container_client.list_blobs(f"{application_major}.")
    for blob in blob_names:
        for d in app_dependencies:
            if symbol_name(app_dependencies["name"]) in symbol_name(blob.name):
                download_blob(blob_container_client, blob.name, DownloadPathDestination)

    return DownloadPathDestination


def process_app_file(
    app_json_filepath: str, repo_name: str, event_name: str, commit: str, work_path: str
):
    """Process a single app.json file and build the app"""

    # If we're processing a variant app.json, temporarily make it the main app.json
    temp_app_json = None
    if app_json_filepath.name != "app.json":
        temp_app_json = Path(work_path) / "app.json"
        if temp_app_json.exists():
            temp_backup = Path(work_path) / "app.json.bak"
            shutil.copy(temp_app_json, temp_backup)
        shutil.copy(app_json_filepath, temp_app_json)
        app_json_filepath = temp_app_json

    # Read app.json file
    with open(app_json_filepath, "r") as f:
        app_file = json.load(f)

    # Construct new version
    today = datetime.datetime.now()
    start_date = datetime.datetime(2020, 1, 1)
    days_since_start = (today - start_date).days
    out_version_major = app_file["platform"].split(".")[0]
    out_version_minor = today.strftime("%y")
    out_version_build = str(days_since_start)
    out_version_revision = str(
        int((today - today.replace(hour=0, minute=0, second=0)).total_seconds() / 60)
    )

    # Set version based on build type
    if event_name == "push":
        out_version = f"{out_version_major}.{out_version_minor}.{out_version_build}.{out_version_revision}"
    else:
        out_version = "0.0.0.0"

    # Update app.json with new version
    app_file["version"] = out_version

    # Save modified app.json
    with open(app_json_filepath, "w") as f:
        json.dump(app_file, f, indent=2)

    # Construct output app filename
    out_file = (
        f"{symbol_name(app_file['name'])}_{out_version}_{commit[:7]}_unsigned.app"
    )

    # Compile the app
    # Set AL compiler variables
    ruleset = os.path.join(work_path, "LincRuleSet.json")
    target = app_file["target"]
    application_major = app_file["application"].split(".")[0]
    app_dependencies = app_file["dependencies"]
    generate_report_layout = "-"
    error_log = "errorLog.json"

    # Handle permission files
    if float(app_file["runtime"]) >= 8.1:
        permission_path = os.path.join(work_path, "extensionsPermissionSet.xml")
        if os.path.exists(permission_path):
            os.remove(permission_path)
    else:
        for f in Path(work_path).glob("PermissionSet*.al"):
            if os.path.exists(f):
                os.remove(f)

    # Collect Microsoft symbols and dependencies
    symbols_location = get_symbols(application_major, app_dependencies)

    # Run AL compiler
    alc_path = os.path.join(".", "alc", "extension", "bin", "linux", "alc")
    if os.path.exists(alc_path):
        cmd = [
            alc_path,
            f"/packagecachepath:{symbols_location}",
            f"/project:{work_path}",
            f"/out:{out_file}",
            f"/target:{target}",
            "/loglevel:Verbose",
            f"/errorlog:{error_log}",
            f"/generatereportlayout:{generate_report_layout}",
            f"/ruleset:{ruleset}",
        ]

        # Run AL compiler
        process = subprocess.run(cmd)

        # Check if build was successful
        if process.returncode == 0:
            if event_name == "push":  # Production build
                print(f"Successful Compile: {app_file['name']} at commit {commit[:7]}")
                # Sign the app file
                print(f"Signing {out_file}...")
                source = out_file

                # azuresigntool sign -kvu [vault uri] -kvc [certificate name] -kvi [application id] -kvs [secret] -kvt [tenant id] -tr http://timestamp.digicert.com -v [filename.exe]
                sign_cmd = [
                    "azuresigntool",
                    "sign",
                    "-kvu",
                    os.environ.get("AZURE_KEY_VAULT_URI"),
                    "-kvc",
                    os.environ.get("AZURE_KEY_VAULT_CERTIFICATE_NAME"),
                    "-kvi",
                    os.environ.get("AZURE_KEY_VAULT_APPLICATION_ID"),
                    "-kvs",
                    os.environ.get("AZURE_KEY_VAULT_APPLICATION_SECRET"),
                    "-kvt",
                    os.environ.get("AZURE_KEY_VAULT_TENANT_ID"),
                    "-tr",
                    "http://timestamp.digicert.com",
                    "-v",
                    source,
                ]
                signprocess = subprocess.run(sign_cmd, stdout=subprocess.DEVNULL)

                # Check if signing was successful
                if signprocess.returncode != 0:
                    print(f"Error signing {out_file}")
                    sys.exit(1)
                else:
                    # Upload the app file to Azure Blob Storage
                    connection_string = os.getenv("AZ_CONNECTION_STRING")
                    container_name = os.getenv("AZ_CONTAINER_NAME_DEPENDENCIES")
                    blob_name = (
                        f"{application_major}/{symbol_name(repo_name)}/{out_file}"
                    )
                    blob_service_client = BlobServiceClient.from_connection_string(
                        connection_string
                    )
                    blob_client = blob_service_client.get_blob_client(
                        container=container_name, blob=blob_name
                    )
                    with open(source, "rb") as data:
                        blob_client.upload_blob(data, overwrite=True)
                    # Set GitHub environment variable for build number
                    build_number = f"{out_version}_{commit[:7]}"
                    print(
                        f"Successful Build: {app_file['name']} version {out_version} at commit {commit[:7]}"
                    )
            else:  # Test compile
                source = os.path.join(out_file)
                if os.path.exists(source):
                    os.remove(source)
                print(
                    f"Successful Compile Test: {app_file['name']} at commit {commit[:7]}"
                )
        else:
            print(f"Error compiling {app_file['name']} at commit {commit[:7]}")
            print(f"ALC return code: {process.returncode}")
            sys.exit(1)

    # Restore original app.json file if we used a temporary one
    if temp_app_json:
        shutil.copy(Path(work_path) / "app.json.bak", Path(work_path) / "app.json")
        os.remove(Path(work_path) / "app.json.bak")


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Build AL application")
    parser.add_argument(
        "-r",
        "--repo",
        type=str,
        help="Name of the git repository",
        required=True,
    )
    parser.add_argument(
        "-e",
        "--event",
        type=str,
        help="Name of the event",
        required=False,
    )
    parser.add_argument("-c", "--commit", type=str, help="Commit hash")
    args = parser.parse_args()
    repo_name = args.repo
    event_name = args.event
    commit = args.commit

    # Load environment variables
    dotenv.load_dotenv()

    # Find files of pattern *app.json and iterate over them
    if os.environ.get("WORK_PATH"):
        work_path = os.environ.get("WORK_PATH")
    else:
        work_path = os.getcwd()
    print(f"Working path: {work_path}")
    app_json_files = list(Path(work_path).glob("*app.json"))

    if not app_json_files:
        print("No app.json files found in the current directory")
        sys.exit(1)

    print(f"Found {len(app_json_files)} app.json file(s)")

    for app_json_file in app_json_files:
        print(f"Processing {app_json_file}")
        process_app_file(app_json_file, repo_name, event_name, commit, work_path)


if __name__ == "__main__":
    main()
