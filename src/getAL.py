import os
import zipfile
import dotenv
from azure.storage.blob import BlobServiceClient, BlobClient


def DownloadBlob(blob_client: BlobClient, blob_name, DownloadDestination):
    print(f"Starting download of {blob_name}...")

    # Download with progress tracking
    with open(DownloadDestination, "wb") as download_file:
        download_stream = blob_client.download_blob()
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


def download_AL():  # Download URL for ALC portable:
    dotenv.load_dotenv()

    # Azure Blob Storage settings
    connection_string = os.getenv("AZ_CONNECTION_STRING")
    container_name = os.getenv("AZ_CONTAINER_NAME_TOOLS")
    al_blob_name = os.getenv("AZ_ALC_FILENAME")

    print("Downloading AL Compiler from Azure Storage...")

    # Create the download destination
    DownloadPathDestination = "../alc"
    if not os.path.exists(DownloadPathDestination):
        os.mkdir(DownloadPathDestination)

    # Download from Azure Blob Storage
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)

    # Download ALC
    blob_client = blob_service_client.get_blob_client(
        container=container_name, blob=al_blob_name
    )
    DownloadZipDestination = os.path.join(DownloadPathDestination, "alc.zip")
    DownloadBlob(blob_client, al_blob_name, DownloadZipDestination)

    # Unzip alc portable, and then delete the zip file:
    with zipfile.ZipFile(DownloadZipDestination, "r") as zip_ref:
        zip_ref.extractall(DownloadPathDestination)
    os.remove(DownloadZipDestination)

    chmod_path = os.path.join(DownloadPathDestination, "linux/alc")
    os.chmod(chmod_path, 0o755)

    return os.path.join(DownloadPathDestination, "linux/")


if __name__ == "__main__":
    # main part of script
    print(download_AL())
