import os
import json
import glob
import argparse
import requests
import sys
from pathlib import Path


class AuthContext:
    """Python equivalent to BcContainerHelper auth functions"""

    @staticmethod
    def new_bc_auth_context(client_id, client_secret, scopes, tenant_id):
        """Python equivalent to New-BcAuthContext from BcContainerHelper"""
        auth_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scopes,
            "grant_type": "client_credentials",
        }

        response = requests.post(auth_url, data=payload)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Authentication failed: {response.text}")


class AppSource:
    """Python equivalent to AppSource functions from BcContainerHelper"""

    @staticmethod
    def get_appsource_product(auth_context, silent=True):
        """Python equivalent to Get-AppSourceProduct from BcContainerHelper"""
        headers = {
            "Authorization": f"Bearer {auth_context['access_token']}",
            "Content-Type": "application/json",
        }

        api_url = "https://api.partner.microsoft.com/v1.0/products"

        response = requests.get(api_url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            if not silent:
                print(f"Failed to get products: {response.text}")
            return []

    @staticmethod
    def new_appsource_submission(
        auth_context,
        product_id,
        app_file,
        library_app_files=None,
        auto_promote=True,
        do_not_wait=True,
    ):
        """Python equivalent to New-AppSourceSubmission from BcContainerHelper"""
        headers = {
            "Authorization": f"Bearer {auth_context['access_token']}",
        }

        api_url = (
            f"https://api.partner.microsoft.com/v1.0/products/{product_id}/submissions"
        )

        # Prepare files for upload
        files = {"appFile": open(app_file, "rb")}

        if library_app_files:
            files["libraryAppFiles"] = open(library_app_files, "rb")

        data = {
            "autoPromote": "true" if auto_promote else "false",
            "doNotWait": "true" if do_not_wait else "false",
        }

        try:
            response = requests.post(api_url, headers=headers, files=files, data=data)
            if response.status_code in [200, 201, 202]:
                print("AppSource submission initiated successfully")
                return response.json()
            else:
                raise Exception(f"Submission failed: {response.text}")
        finally:
            # Close file handles
            for f in files.values():
                f.close()


def main(git_repo_name):
    # Set working directories
    build_root = r"C:\Linc-GithubWorkflows\AppBuilds"
    work_path = os.path.join(r"C:\actions-runner\_work", git_repo_name, git_repo_name)

    # Get app.json file of project
    app_json_filepath = os.path.join(work_path, "app.json")

    # Read app.json file into variables for later use
    try:
        with open(app_json_filepath, "r") as f:
            app_json_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error parsing app.json: {str(e)}")
        return 1
    except FileNotFoundError:
        print(f"Error: app.json not found at {app_json_filepath}")
        return 1

    app_dependencies = app_json_data.get("dependencies", [])
    app_name = app_json_data["name"].replace(" ", "-").replace("-", "")
    app_source_path = os.path.join(build_root, app_name)

    # Check dependencies for Linc Extension Access
    has_library_file = False
    library_source_path = None

    for d in app_dependencies:
        if d["name"].replace(" ", "-").replace("-", "") == "LincExtensionAccess":
            library_source_path = os.path.join(
                build_root, d["name"].replace(" ", "-").replace("-", "")
            )
            has_library_file = True

    # Set product name to search for on marketplace offers
    product_name = app_json_data["name"].replace("-", " ").replace("Linc ", "")

    # Set valid names for app and library files
    app_file_path = os.path.join(app_source_path, "*.app")
    app_files = glob.glob(app_file_path)

    if not app_files:
        print(f"Error: No .app files found at {app_source_path}")
        return 1

    app_file = app_files[0]  # Get the first matching .app file

    lib_app_file = None
    if has_library_file:
        lib_app_file_path = os.path.join(library_source_path, "*.app")
        lib_app_files = glob.glob(lib_app_file_path)

        if not lib_app_files:
            print(f"Error: No library .app files found at {library_source_path}")
            return 1

        lib_app_file = lib_app_files[0]

    # Publish to appsource
    tenant_id = "9d9672cd-de63-40b4-923d-3651563114a2"
    client_id = "7bb201ba-ae54-4c5e-b470-28826e397a9b"
    client_secret = "jN38Q~005vNI8BYDNjgvqRshg3KHaOiy2f8oAcgv"

    try:
        # Authenticate
        auth_context = AuthContext.new_bc_auth_context(
            client_id=client_id,
            client_secret=client_secret,
            scopes="https://api.partner.microsoft.com/.default",
            tenant_id=tenant_id,
        )

        # Get products and find product ID
        products = AppSource.get_appsource_product(auth_context, silent=True)
        product_id = next(
            (p["id"] for p in products if p["name"] == product_name), None
        )

        if not product_id:
            print("Unable to find existing AppSource product")
            return 1
        else:
            # Submit to AppSource
            if has_library_file:
                AppSource.new_appsource_submission(
                    auth_context=auth_context,
                    product_id=product_id,
                    app_file=app_file,
                    library_app_files=lib_app_file,
                    auto_promote=True,
                    do_not_wait=True,
                )
            else:
                AppSource.new_appsource_submission(
                    auth_context=auth_context,
                    product_id=product_id,
                    app_file=app_file,
                    auto_promote=True,
                    do_not_wait=True,
                )
            return 0

    except Exception as e:
        print(f"Error during AppSource submission: {str(e)}")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Process GitHub repository for AppSource submission."
    )
    parser.add_argument(
        "git_repo_name", type=str, help="The GitHub repository name running the action"
    )

    args = parser.parse_args()
    sys.exit(main(args.git_repo_name))
