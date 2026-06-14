import os
import fal_client
import requests
import mimetypes
from dotenv import load_dotenv
import logging as log 


DEFAULT_VISION_ENDPOINT = "openrouter/router/vision"
DEFAULT_VISION_MODEL = "google/gemini-2.5-flash" 
DEFAULT_VIDEO_ENDPOINT = "fal-ai/ltx-2.3/image-to-video/fast"


DEFAULT_VOICE_ID = "b8jhBTcGAq4kQGWmKprT" 
ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

load_dotenv()

def generate_video_single(image_path, duration, output_path, prompt=None, model_endpoint=DEFAULT_VIDEO_ENDPOINT, test_mode = False):
    """
    Generates a single video with specific parameters.
    """
    if not os.path.exists(image_path):
        log.error("Image not found")

    log.info(f"\nProcessing: {image_path}")

    try:
        # Upload Image
        log.info("  [1/4] Uploading image to Fal.ai storage...")
        image_url = fal_client.upload_file(image_path)
        
        # Vision Model 
        log.info("  [2/4] Analyzing image with Vision model...")
        
        # Construct request for vision model
        vision_prompt = (
            "Based on this image high-quality prompt for an 8s video generation model. "
            "Be succint, not verbose; A good prompt should ideally be short"
            "The video should be a simple animation of the image"
            "Showcase items in frame, do not add any new items or people."
            "Output ONLY the final video generation prompt, nothing else."
        )
        
        # add hint
        if not test_mode:
            if prompt:
                vision_prompt += f" \nIMPORTANT style/context instruction: {prompt}"

            vision_result = fal_client.subscribe(
                DEFAULT_VISION_ENDPOINT,
                arguments={
                    "image_urls": [image_url],
                    "prompt": vision_prompt,
                    "model": DEFAULT_VISION_MODEL
                }
            )
            print(vision_result)
        
        # Extract the generated text
            generated_prompt = vision_result.get('output', '').strip()
            log.info(f"  --> Generated Prompt: \"{generated_prompt}\"")

            if not generated_prompt:
                log.error("  Error: Vision model returned empty prompt. Using fallback.")
                generated_prompt = "A cinematic video of this scene, high quality, 4k"

        # Video Generation
        log.info(f"  [3/4] Generating video using {model_endpoint}...")

        result = None

        if not test_mode:

            while (duration in [6, 8, 10, 12, 14, 16, 18, 20]) == False:
                duration += 1
                if duration > 20:
                    duration = 20

        
            video_handler = fal_client.submit(
                model_endpoint,
                arguments={
                    "image_url": image_url,
                    "prompt": generated_prompt,
                    "duration": duration
                }
            )
            result = video_handler.get()

            print (result)

        # Download
        if result != None:
            if 'video' in result and 'url' in result['video']:
                video_url = result['video']['url']
                log.info("  [4/4] Video generated successfully. Downloading...")
                download_video(video_url, output_path)
                return True

        elif test_mode:
            video_url = "https://v3b.fal.media/files/b/0a8866f6/dmGBclH_CBmaku8J31ZE8_output.mp4"
            log.info("defaulting...")
            download_video(video_url, output_path)
            return True

        else:
            log.error(f"  Error: No video URL returned. Result: {result}")

    except Exception as e:
        log.error(f"  Error processing {image_path}: {e}")

def mass_generation(
    image_dict, 
    duration = 5,
    model_endpoint = DEFAULT_VIDEO_ENDPOINT, 
    test_mode = False):
    """
    1. Uploads local images to Fal.
    2. Uses a Vision model to generate a custom cinematic prompt.
    3. Sends the image + generated prompt to the Video generation API.
    4. Downloads the result.

    Args:
        image_dict (dict): { "path/to/image.jpg": "Optional hint (or None)" }
        model_endpoint (str): The video generation model endpoint.
        duration (str): Duration (e.g., "5s"). Different models have different options, so check documentation.
        download_path (str): Folder to save downloaded videos.
    """
    
    if not os.environ.get("FAL_KEY"):
        log.critical("Error: FAL_KEY not found. Check .env")
        return

    total = len(image_dict)
    
    for i, (image_path, user_hint) in enumerate(image_dict.items(), 1):
        generate_video_single(image_path, user_hint, duration, output_path, model_endpoint=model_endpoint, test_mode=False)
        
    return 


def download_video(url, output_path):
    """Downloads video directly to a specific file path."""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"  Saved to: {output_path}")
    except Exception as e:
        print(f"  Failed to download: {e}")



if __name__ == "__main__":

    image_file_1 = "testing_tools/input_videos/davide.jpg"
    image_file_2 = "testing_tools/input_videos/retrospettiva.jpg"
    image_file_3 = "testing_tools/input_videos/testaccio.jpg"
    image_dict = {image_file_1:None, image_file_2: None, image_file_3: None}

    mass_generation(image_dict)