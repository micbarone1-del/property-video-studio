import time
import glob
import os
import pandas as pd
import requests
import re
import traceback
from communication import download_and_process_latest_spreadsheet, send_custom_email
# Import the pipeline steps from your main script
from video_assembly import run_content_generation, run_editor
import logging as log

# --- Configuration ---
DOWNLOADS_DIR = "downloads"
IMAGE_INPUT_DIR = "image_input"
VIDEO_INPUT_DIR = "video_input"
OUTPUT_VIDEO = "final_story.mp4"

def get_google_drive_direct_link(url):
    """Converts a Google Drive view link to a direct download link."""
    if "drive.google.com" in url:
        # Extract ID
        file_id_match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
        if file_id_match:
            file_id = file_id_match.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url

def download_asset(url, folder, item_name):
    """
    Downloads a file from a URL to the specified folder.
    Renames it to item_name, preserving or guessing the extension.
    """
    try:
        # Normalize URL (Handle Google Drive)
        direct_url = get_google_drive_direct_link(url)
        
        print(f"  Downloading: {item_name} from {url[:30]}...")
        response = requests.get(direct_url, stream=True)
        response.raise_for_status()
        
        # Determine Extension
        content_type = response.headers.get('content-type', '')
        if 'video' in content_type:
            ext = '.mp4'
        elif 'image' in content_type:
            ext = '.png' # Default fallback for images
        else:
            # Try to get from original URL
            ext = os.path.splitext(url.split('?')[0])[1]
            if not ext: ext = '.mp4' # Blind fallback

        # Construct local path
        filename = f"{item_name}{ext}"
        file_path = os.path.join(folder, filename)
        
        # Save
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                
        return file_path, filename
    except Exception as e:
        print(f"  [Download Error] Failed to download {url}: {e}")
        return None

def prepare_pipeline_config(spreadsheet_path):
    """
    
    Reads the Excel file, downloads assets, and builds the config dictionary for main.py.
    """
    df = pd.read_excel(spreadsheet_path)
    # Normalize headers
    df.columns = [c.lower().strip() for c in df.columns]
    
    scenes_config = []
    
    for index, row in df.iterrows():
        item_name = str(row.get('item_name', '')).strip()
        if not item_name or item_name.lower() == 'nan':
            continue
            
        print(f"\nProcessing Row: {item_name}")
        
        # 1. Determine Download Source
        video_link = str(row.get('video_link', '')) if not pd.isna(row.get('video_link')) else ''
        image_link = str(row.get('image_link', '')) if not pd.isna(row.get('image_link')) else ''
        only_video = bool(row.get('only_video', False))
        
        local_path = None
        target_folder = IMAGE_INPUT_DIR
        is_video_asset = False
        
        # Logic: Check links and only_video flag
        download_url = None
        
        if video_link and image_link:
            if only_video:
                download_url = video_link
                target_folder = VIDEO_INPUT_DIR
                is_video_asset = True
            else:
                download_url = image_link
                target_folder = IMAGE_INPUT_DIR
        elif video_link:
            download_url = video_link
            target_folder = VIDEO_INPUT_DIR
            is_video_asset = True
        elif image_link:
            download_url = image_link
            target_folder = IMAGE_INPUT_DIR

        # 2. Download File
        if download_url:
            local_path, filename = download_asset(download_url, target_folder, item_name)

        print(local_path)
        print(filename)
        
        # 3. Build Scene Dictionary
        scene_data = {
            "item_name": filename,
            "title": str(row.get('title', '')) if not pd.isna(row.get('title')) else "",
            "caption": str(row.get('caption', '')) if not pd.isna(row.get('caption')) else "",
            "video_hint": str(row.get('video_hint', '')) if not pd.isna(row.get('video_hint')) else "",
            "text_direction": str(row.get('text_direction', 'left')),
            "effects_duration": float(row.get('effects_duration', 0.5)),
            "video_redo": bool(row.get('video_redo', False)),
            "tts": bool(row.get('tts', False)),
            "tts_redo": bool(row.get('tts_redo', False)),
            "only_video": only_video
        }
        
        # Explicitly inject the path so main.py finds it easily
        if local_path:
            if is_video_asset:
                scene_data["video_path"] = local_path # For existing video assets
                scene_data["only_video"] = True # Reinforce this for main.py logic
            else:
                scene_data["image_path"] = local_path # For AI generation source

        scenes_config.append(scene_data)
        
    return {"scenes": scenes_config, "final_filename": OUTPUT_VIDEO}

def run_workflow():
    print("Starting Continuous Automation Process... (Press Ctrl+C to stop)")

    # Ensure directories exist
    for d in [DOWNLOADS_DIR, IMAGE_INPUT_DIR, VIDEO_INPUT_DIR]:
        if not os.path.exists(d):
            os.makedirs(d)

    while True:
        try:
            # Step 1: Check for new spreadsheets
            # NOTE: Assuming this returns the SENDER EMAIL (str) if successful, None if not.
            client_email = download_and_process_latest_spreadsheet()

            if client_email:
                print(f"New file received from {client_email}")

                # Step 2: Send Confirmation Email
                send_custom_email(
                    client_email,
                    "Confirmation: File Received",
                    "Hello! We received your spreadsheet. Downloading assets and starting video generation now."
                )

                # Find the downloaded file
                archive_list = glob.glob(os.path.join(DOWNLOADS_DIR, "*.xlsx"))
                if not archive_list:
                    print("Error: Success reported but no .xlsx file found.")
                    continue
                
                spreadsheet_path = max(archive_list, key=os.path.getmtime)
                print(f"Reading file: {spreadsheet_path}")

                try:
                    # Step 3: Prepare Config (Download & Rename assets)
                    config_data = prepare_pipeline_config(spreadsheet_path)
                    
                    if not config_data["scenes"]:
                        print("No valid scenes found in spreadsheet.")
                        raise ValueError("Spreadsheet was empty or invalid.")

                    # Step 4: Run the Main Pipeline
                    print("--- Running Content Generation ---")
                    run_content_generation(config_data)
                    
                    print("--- Running Video Editor ---")
                    final_name = run_editor(config_data)
                    
                    if final_name == None:
                        raise Exception("No valid video found")

                    # Step 5: Send Success Email
                    if os.path.exists(OUTPUT_VIDEO):
                        print("Sending success email with attachment...")
                        send_custom_email(
                            client_email,
                            "Video Generation Complete",
                            "Your video has been successfully generated! Please see the attached file.",
                            attachment_path=final_name
                        )
                        print("Workflow completed successfully.")
                        
                        # Cleanup (Optional: Move/Delete processed excel)
                        # os.remove(spreadsheet_path) 
                    else:
                        raise Exception("The output video file was not found after processing.")

                except Exception as process_error:
                    error_message = f"An error occurred: {str(process_error)}"
                    print(error_message)
                    traceback.print_exc()
                    
                    # Send Error Email
                    send_custom_email(
                        client_email,
                        "Error in Video Generation",
                        f"We encountered an issue while processing your request:\n\n{str(process_error)}"
                    )
            
            # Reduce CPU usage
            time.sleep(10)

        except KeyboardInterrupt:
            print("\nStopping automation.")
            break
        except Exception as e:
            print(f"Unexpected loop error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    log.basicConfig(level=log.DEBUG)
    run_workflow()