import os
import textwrap
import math
import numpy as np
from moviepy import (
    VideoFileClip, 
    ImageClip, 
    TextClip, 
    CompositeVideoClip, 
    ColorClip, 
    AudioFileClip,
    concatenate_videoclips,
    vfx
)

# Helpers before main functionality
# Cropping function

def resize_and_crop(clip, target_w, target_h):
    """
    Resizes the clip to fill the target dimensions while maintaining aspect ratio,
    then center crops the excess. This prevents aspect ratio mismatches.
    """
    w, h = clip.w, clip.h
    
    # Avoid division by zero
    if h == 0 or target_h == 0:
        return clip

    target_ratio = target_w / target_h
    current_ratio = w / h
    
    if current_ratio > target_ratio:
        # Resize based on Height to fill vertically, then crop width.
        new_clip = clip.resized(height=target_h)
    else:
        # Resize based on Width to fill horizontally, then crop height.
        new_clip = clip.resized(width=target_w)
        
    # Center crop to exact target dimensions
    return new_clip.cropped(width=target_w, height=target_h, x_center=new_clip.w / 2, y_center=new_clip.h / 2)

def create_gradient_bar(width, height, direction='left', color=(0,0,0), max_opacity=0.8):
    """
    Creates a gradient bar (RGBA) for text background using numpy.
    Supports left, right, top, and bottom fade directions.
    """
    w, h = int(width), int(height)
    
    if w <= 0 or h <= 0:
        return ColorClip(size=(max(1, w), max(1, h)), color=(0,0,0,0))

    if direction in ['left', 'right']:
        x = np.linspace(0, 1, w)
        if direction == 'left':
            alpha_row = (1 - x) * 255 * max_opacity
        else: # right
            alpha_row = x * 255 * max_opacity
            
        alpha_row = alpha_row.reshape(1, w)
        alpha = np.tile(alpha_row, (h, 1))
    else:
        y = np.linspace(0, 1, h)
        if direction == 'top':
            alpha_col = (1 - y) * 255 * max_opacity
        else: # bottom
            alpha_col = y * 255 * max_opacity
            
        alpha_col = alpha_col.reshape(h, 1)
        alpha = np.tile(alpha_col, (1, w))
    
    r = np.full((h, w), color[0])
    g = np.full((h, w), color[1])
    b = np.full((h, w), color[2])
    
    img_array = np.dstack((r, g, b, alpha)).astype(np.uint8)
    
    return ImageClip(img_array)

def create_text_clip(text, font, fontsize, color, size, align='left', stroke_color=None, stroke_width=0):
    """
    Creates a TextClip with robust error handling for missing fonts and wrapping.
    Supports both MoviePy 1.x and 2.x alignment parameters to guarantee it won't be incorrectly centralized.
    """
    if not text:
        return None

    safe_width_px = int(size[0]) if size[0] else 1000
    avg_char_width = fontsize * 0.5 
    max_chars_per_line = max(1, int(safe_width_px / avg_char_width))
    
    if len(text) > max_chars_per_line:
        final_text = textwrap.fill(text, width=max_chars_per_line)
    else:
        final_text = text
    
    final_text = final_text + "\n"

    kwargs = {
        'color': color,
        'font': font,
        'method': 'label',
        'stroke_color': stroke_color,
        'stroke_width': stroke_width
    }

    try:
        try:
            # MoviePy 2.x Signature (Prevents Engine from auto-centering text)
            clip = TextClip(
                text=final_text, 
                font_size=fontsize, 
                text_align=align,
                horizontal_align=align,
                **kwargs
            )
        except (TypeError, AttributeError):
            # MoviePy 1.x Fallback
            clip = TextClip(
                txt=final_text, 
                fontsize=fontsize, 
                align=align,
                **kwargs
            )
            
        if clip.w == 0 or clip.h == 0:
            print(f"[WARNING] Generated TextClip has 0 dimensions.")
            return None
            
        return clip

    except Exception as e:
        print(f"\n[ERROR] Failed to render text: '{text[:10]}...' - {e}")
        return None

def create_sidebar_clip(width, height, direction, title, caption, title_font='BebasNeue-Regular', title_size=48, caption_font='Arial', caption_size=20):
    """
    Creates a composite clip containing the gradient background and text.
    Adapts layout dynamically to left, right, top, or bottom positioning.
    """
    # 1. Establish Layout based on orientation
    if direction in ['left', 'right']:
        bg_width = int(width * 1.2) 
        bg_height = height
        text_width = int(width * 0.8)
        padding_x = int(width * 0.1)
        padding_y = int(height * 0.1)
        txt_align = 'left'
    else: # top, bottom
        bg_width = width
        bg_height = int(height * 1.2)
        text_width = int(width * 0.8) # Constrain text to 80% of screen width
        padding_x = int(width * 0.1)
        padding_y = int(height * 0.1)
        txt_align = 'left'

    bg_clip = create_gradient_bar(bg_width, bg_height, direction=direction)
    layers = [bg_clip]
    
    # 2. Pre-create Text Clips to know their exact height
    t_clip = None
    c_clip = None
    total_text_h = 0
    
    if title:
        t_clip = create_text_clip(title, title_font, title_size, color='white', size=(text_width, None),
                                  align=txt_align, stroke_color='black', stroke_width=2)
        if t_clip: total_text_h += t_clip.h
        
    if caption:
        c_clip = create_text_clip(caption, caption_font, caption_size, color='yellow', size=(text_width, None),
                                  align=txt_align, stroke_color='black', stroke_width=1)
        if c_clip: total_text_h += c_clip.h
        
    if t_clip and c_clip:
        total_text_h += 20 # Padding between title and caption

    # 3. Determine starting vertical cursor
    if direction in ['left', 'right', 'top']:
        current_y = padding_y
    else: # bottom
        # Solid dark color is at the absolute bottom edge of bg_height
        current_y = bg_height - padding_y - total_text_h

    # 4. Apply Position and Compose
    if t_clip:
        if direction == 'left': x_pos = padding_x
        elif direction == 'right': x_pos = bg_width - t_clip.w - padding_x
        else: x_pos = padding_x # Left-aligned for top/bottom with padding
            
        t_clip = t_clip.with_position((x_pos, current_y))
        layers.append(t_clip)
        current_y += t_clip.h + 20
            
    if c_clip:
        if direction == 'left': x_pos = padding_x
        elif direction == 'right': x_pos = bg_width - c_clip.w - padding_x
        else: x_pos = padding_x # Left-aligned for top/bottom with padding

        c_clip = c_clip.with_position((x_pos, current_y))
        layers.append(c_clip)

    return CompositeVideoClip(layers, size=(bg_width, bg_height))

def create_box_clip(width, title, caption, duration, title_font='BebasNeue-Regular', title_size=48, caption_font='Arial', caption_size=40, padding=20):
    """
    Creates a composite clip with solid box backgrounds for a 'news-style' lower third. 
    Title adjusts height dynamically. Caption is a single line and scrolls right-to-left.
    """
    # Exact colors matching the reference image layout
    title_bg_color = (43, 43, 51)      # Dark grey
    caption_bg_color = (245, 245, 245) # Light grey / off-white
    news_bg_color = (43, 43, 51)       # Darkest grey for NEWS square
    
    # We pull your exact heights up here to calculate the perfect square
    title_h = 90 if title else 0
    caption_h = 70 if caption else 0
    total_h = title_h + caption_h
    
    if total_h == 0:
        return None
        
    news_size = total_h - 10
    content_w = width
    gap = 32 # The gap to keep the NEWS square completely separate
    
    # 1. Process Title
    title_comp = None
    if title:
        safe_title_width = content_w - (padding * 2)
        
        # Render a test clip at the requested max size without wrapping to measure true width
        t_clip = create_text_clip(title, title_font, title_size, color='white', size=(99999, None), align='left')
        
        dynamic_title_size = title_size
        if t_clip and t_clip.w > safe_title_width:
            # Scale down proportionally to perfectly fit the available width
            dynamic_title_size = int(title_size * (safe_title_width / max(1, t_clip.w)))
            # Re-render with the new exact size
            t_clip = create_text_clip(title, title_font, dynamic_title_size, color='white', size=(99999, None), align='center')

        if t_clip:
            title_bg = ColorClip(size=(content_w, title_h), color=title_bg_color).with_duration(duration)
            # Center vertically perfectly based on actual height
            y_pos = max(0, (title_h - t_clip.h) / 2)
            t_clip = t_clip.with_duration(duration).with_position((padding, padding))
            title_comp = CompositeVideoClip([title_bg, t_clip], size=(content_w, title_h))
            
    # 2. Process Caption
    caption_comp = None
    if caption:
        try:
            # Pass a huge width so it stays on one line.
            c_clip = create_text_clip(caption + "   ", caption_font, caption_size, color='black', size=(99999, None), align='left')
            if not c_clip:
                # Blind Fallback
                try:
                    c_clip = TextClip(text=caption + "   ", font_size=caption_size, color='black', font=caption_font, method='label')
                except TypeError:
                    c_clip = TextClip(txt=caption + "   ", fontsize=caption_size, color='black', font=caption_font, method='label')
                    
            caption_bg = ColorClip(size=(content_w, caption_h-10), color=caption_bg_color).with_duration(duration)
            
            c_w = c_clip.w
            def scroll_func(t):
                # Calculate speed so it traverses exactly within the scene's duration
                speed = (content_w + c_w) / max(duration, 0.1)
                x = content_w - int(t * speed)
                return (x, 10)
                
            c_clip = c_clip.with_duration(duration).with_position(scroll_func)
            caption_comp = CompositeVideoClip([caption_bg, c_clip], size=(content_w, caption_h))
        except Exception as e:
            print(f"[ERROR] Failed to render scrolling caption: {e}")
            
    layers = []
    
    # Layer 1: NEWS Square Block (Left side)
    news_bg = ColorClip(size=(news_size, news_size), color=news_bg_color).with_duration(duration)
    news_text = create_text_clip("NEWS", title_font, int(55), color='white', size=(news_size, news_size), align='center')
    if news_text:
        news_text = news_text.with_position(("center", 40)).with_duration(duration)
        news_comp = CompositeVideoClip([news_bg, news_text], size=(news_size, news_size))
    else:
        news_comp = news_bg
        
    layers.append(news_comp.with_position((0, 0)))
    
    # Layer 2: Title block (Shifted right by news_size + gap to keep it entirely separate)
    if title_comp:
        layers.append(title_comp.with_position((news_size + gap, 0)))
        
    # Layer 3: Caption block below Title block
    if caption_comp:
        layers.append(caption_comp.with_position((news_size + gap, title_h)))
        
    # Set the total bounding box wide enough to hold both the original bar and the new square
    total_w = news_size + gap + content_w
    return CompositeVideoClip(layers, size=(total_w, total_h)).with_duration(duration)

class VideoCompositor:
    def __init__(self, base_video_path):
        if not os.path.exists(base_video_path):
            raise FileNotFoundError(f"Video file not found: {base_video_path}")
            
        self.base_clip = VideoFileClip(base_video_path)
        self.elements = [self.base_clip]
        self.duration = self.base_clip.duration
        self.video_width = self.base_clip.w
        self.video_height = self.base_clip.h

    def apply_base_transitions(self, fade_in=0, fade_out=0, color=(0,0,0)):
        effects = []
        if fade_in > 0:
            effects.append(vfx.FadeIn(duration=fade_in, initial_color=color))
        if fade_out > 0:
            effects.append(vfx.FadeOut(duration=fade_out, final_color=color))
        
        if effects:
            self.elements[0] = self.elements[0].with_effects(effects)

    def add_image_overlay(self, image_path, start_time=0, duration=None, 
                          position=('center', 'center'), opacity=1.0, scale=1.0,
                          fade_in=0.0, fade_out=0.0):
        if not os.path.exists(image_path):
            print(f"Warning: Image path {image_path} not found.")
            return

        new_clip = ImageClip(image_path)
        final_duration = duration if duration else (self.duration - start_time)
        new_clip = new_clip.with_start(start_time).with_duration(final_duration)

        if scale != 1.0:
            new_clip = new_clip.resized(scale)
        new_clip = new_clip.with_opacity(opacity).with_position(position)

        effects = []
        if fade_in > 0: effects.append(vfx.CrossFadeIn(duration=fade_in))
        if fade_out > 0: effects.append(vfx.CrossFadeOut(duration=fade_out))
        if effects: new_clip = new_clip.with_effects(effects)

        self.elements.append(new_clip)

    def add_text_overlay(self, text, font='Arial', fontsize=50, color='white', 
                         start_time=0, duration=None, position=('center', 'bottom'), 
                         opacity=1.0, stroke_color=None, stroke_width=0,
                         fade_in=0.0, fade_out=0.0):
        
        txt_clip = create_text_clip(
            text, font, fontsize, color, (self.video_width, None), 
            align='center', stroke_color=stroke_color, stroke_width=stroke_width
        )
        
        if txt_clip:
            final_duration = duration if duration else (self.duration - start_time)
            txt_clip = txt_clip.with_start(start_time).with_duration(final_duration)
            txt_clip = txt_clip.with_opacity(opacity).with_position(position)

            effects = []
            if fade_in > 0: effects.append(vfx.CrossFadeIn(duration=fade_in))
            if fade_out > 0: effects.append(vfx.CrossFadeOut(duration=fade_out))
            if effects: txt_clip = txt_clip.with_effects(effects)

            self.elements.append(txt_clip)

    def render(self, output_path, fps=24):
        final_video = CompositeVideoClip(self.elements, size=self.base_clip.size)
        final_video.write_videofile(output_path, fps=fps, codec='libx264', audio_codec='aac', threads=1)

# --- New Story Sequencer ---
class StorySequencer:
    def __init__(self, output_width=1024, output_height=576):
        self.w = output_width
        self.h = output_height
        self.clips = [] 
        self.current_time = 0.0

    def add_scene(self, video_path, title, caption, title_font ='BebasNeue-Regular.ttf',
                    caption_font = 'Montserrat-Regular.ttf',
                    effects_duration = 0.5,      # Fade animation length
                    text_direction='left',       # 'left', 'right', 'top', 'bottom'
                    audio_path=None,             # Optional audio path
                    image_path=None,             # Fallback image path
                    ui_style='gradient',         # 'gradient' or 'box'
                    box_width_pct=0.88,          # Width of the box as % of screen (0.0 to 1.0)
                    box_bottom_margin=40,        # Pixels from the bottom edge
                    title_size=48,               # Font size for the title
                    caption_size=42,             # Font size for the caption
                    box_padding=20,              # Padding inside the box
                    transition_video_path=None,  # Path to a Green Screen transition file
                    transition_cut_time=0.0,     # Second marking where the transition fully covers the screen
                    transition_audio_path=None,  # Path to the sound effect for the transition
                    logo_path=None               # Defaults to None, letting main.py control the toggle
                    ):
        """
        Creates a composite scene with sliding intro, side-bar text, and optional audio.
        Automatically utilizes a static frame if the audio is over 10s or the video is missing.
        """

        intro_duration = effects_duration
        slide_duration = effects_duration
        fade_duration = effects_duration
        
        is_first_scene = (self.current_time == 0.0)
        has_gs_transition = transition_video_path and os.path.exists(transition_video_path) and not is_first_scene

        # 1. Analyze Audio first to determine if we need Static Mode
        audio_clip = None
        audio_duration = 0.0
        if audio_path and os.path.exists(audio_path):
            audio_clip = AudioFileClip(audio_path)
            audio_duration = audio_clip.duration

        is_static_mode = False
        if audio_duration > 20.0:
            is_static_mode = True
            print(f"  [Static Mode] Audio duration ({audio_duration:.2f}s) > 10s. Forcing static image overlay.")
        elif not video_path or not os.path.exists(video_path):
            if image_path and os.path.exists(image_path):
                is_static_mode = True
                print("  [Static Mode] Video not found. Falling back to static image.")
            else:
                print(f"Skipping scene: Missing video {video_path} and no valid image_path fallback.")
                return

        # 2. Load Visuals
        if is_static_mode:
            # Prefer provided image_path, fallback to extracting frame 0 of the video
            if image_path and os.path.exists(image_path):
                raw_clip = ImageClip(image_path)
            elif video_path and os.path.exists(video_path):
                raw_clip = ImageClip(VideoFileClip(video_path).get_frame(0))
            else:
                print("Skipping scene: No visual source available for static mode.")
                return
            
            # Crop works on both VideoFileClip and ImageClip identically
            visual_clip = resize_and_crop(raw_clip, self.w, self.h)
        else:
            raw_clip = VideoFileClip(video_path)
            visual_clip = resize_and_crop(raw_clip, self.w, self.h)

        # Extract first frame for the Intro Background (if used)
        first_frame = visual_clip.get_frame(0)
        intro_bg = ImageClip(first_frame)

        # 3. Calculate Overlap and Start Time based on Transition Type
        if has_gs_transition:
            # If using a green screen wipe, we hard-cut perfectly at current_time
            scene_start_time = self.current_time
            overlap_time = 0.0
            print(f"Adding scene '{title.strip() if title else 'Untitled'}' at t={scene_start_time:.2f}s (GS Wipe at: {transition_cut_time}s)")
        else:
            # Classic overlap slide
            overlap_time = slide_duration if not is_first_scene else 0.0
            scene_start_time = max(0, self.current_time - overlap_time)
            print(f"Adding scene '{title.strip() if title else 'Untitled'}' at t={scene_start_time:.2f}s (Overlap: {overlap_time}s)")

        # 4. Intro Slide Effect (Bypassed if a Green Screen wipe is handling the transition)
        if not has_gs_transition:
            intro_bg = intro_bg.with_start(scene_start_time).with_duration(intro_duration)
            effects = []
            if fade_duration > 0:
                effects.append(vfx.CrossFadeIn(duration=fade_duration))
            if slide_duration > 0:
                effects.append(vfx.SlideIn(duration=slide_duration, side=text_direction))
            
            if effects:
                intro_bg = intro_bg.with_effects(effects)
            
            self.clips.append(intro_bg)
            video_start_time = scene_start_time + intro_duration
        else:
            # Hard cut into the video under the green screen transition
            video_start_time = scene_start_time

        # 5. Main Video Logic (Audio Handling)
        if is_static_mode:
            # Main visual is the static frame
            main_clip = ImageClip(first_frame)
            if audio_clip:
                main_clip = main_clip.with_duration(audio_clip.duration)
            else:
                main_clip = main_clip.with_duration(5.0) # Default duration if no audio
        else:
            main_clip = visual_clip
            # Handle Video Looping
            if audio_clip:
                if audio_clip.duration > main_clip.duration:
                    loops = math.ceil(audio_clip.duration / main_clip.duration)
                    print(f"  [Looping] Audio ({audio_clip.duration:.2f}s) > Video ({main_clip.duration:.2f}s). Looping {loops} times.")
                    main_clip = concatenate_videoclips([main_clip] * loops)
                # Trim to exact audio length
                main_clip = main_clip.with_duration(audio_clip.duration)
            
        # Attach audio
        if audio_clip:
            main_clip = main_clip.with_audio(audio_clip)

        # Set start time 
        main_clip = main_clip.with_start(video_start_time)
        self.clips.append(main_clip)

        # 6. Process Green Screen Transition early to get its duration
        trans_clip = None
        trans_end_time = video_start_time
        if has_gs_transition:
            try:
                trans_clip = VideoFileClip(transition_video_path)
                trans_clip = resize_and_crop(trans_clip, self.w, self.h)
                
                # Dynamically apply Chroma Key to remove green background
                # Increased threshold and stiffness to eat the green borders (fringe)
                try:
                    # MoviePy 2.x standard parameter names
                    gs_effect = vfx.MaskColor(color=[0, 198, 69], threshold=150, stiffness=15)
                    trans_clip = trans_clip.with_effects([gs_effect])
                except Exception:
                    # Fallback syntax for older/alternative moviepy versions
                    try:
                        gs_effect = vfx.MaskColor(color=[0, 198, 69], thr=150, s=15)
                        trans_clip = trans_clip.with_effects([gs_effect])
                    except Exception:
                        trans_clip = trans_clip.fx(vfx.mask_color, color=[0, 198, 69], thr=150, s=15)
                
                # Apply transition sound effect natively BEFORE shifting the clip's start time
                if transition_audio_path and os.path.exists(transition_audio_path):
                    try:
                        t_audio = AudioFileClip(transition_audio_path)
                        trans_clip = trans_clip.with_audio(t_audio)
                    except Exception as e:
                        print(f"  [ERROR] Failed to attach transition sound: {e}")
                        
                # Offset the transition so the "cut point" perfectly aligns with scene_start_time
                trans_start = scene_start_time - transition_cut_time
                trans_clip = trans_clip.with_start(trans_start)
                trans_end_time = trans_start + trans_clip.duration
                
            except Exception as e:
                print(f"  [ERROR] Failed to apply green screen transition video: {e}")
                has_gs_transition = False

        # 7. Side-Bar Text Overlay
    #   if title or caption:
    #       # Orientation affects text boundaries
    #       if ui_style == 'box':
    #           sidebar_width_target = int(self.w * box_width_pct)
    #           sidebar_height_target = self.h
    #       elif text_direction in ['top', 'bottom']:
    #           sidebar_width_target = self.w
    #           sidebar_height_target = int(self.h * 0.3)
    #       else:
    #           sidebar_width_target = int(self.w * 0.3)
    #           sidebar_height_target = self.h
    #       
    #       text_dur = main_clip.duration
    #       
    #       if ui_style == 'box':
    #           sidebar_clip = create_box_clip(
    #               width=sidebar_width_target,
    #               title=title,
    #               caption=caption,
    #               duration=text_dur,
    #               title_font=title_font,
    #               title_size=title_size,
    #               caption_font=caption_font,
    #               caption_size=caption_size,
    #               padding=box_padding
    #           )
    #       else:
    #           sidebar_clip = create_sidebar_clip(
    #               width=sidebar_width_target,
    #               height=sidebar_height_target,
    #               direction=text_direction,
    #               title=title,
    #               caption=caption,
    #               title_font=title_font,
    #               title_size=title_size,
    #               caption_font=caption_font,
    #               caption_size=caption_size
    #           )
    #       
    #       if sidebar_clip:
    #           # Positioning Logic
    #           if text_direction == 'left':
    #               start_x, final_x = -sidebar_clip.w, 0
    #               start_y, final_y = 0, 0
    #           elif text_direction == 'right':
    #               start_x, final_x = self.w, self.w - sidebar_clip.w
    #               start_y, final_y = 0, 0
    #           elif text_direction == 'top':
    #               if ui_style == 'box':
    #                   start_x = final_x = self.w - sidebar_clip.w
    #                   start_y, final_y = -sidebar_clip.h, box_bottom_margin
    #               else:
    #                   start_x, final_x = 0, 0
    #                   start_y, final_y = -sidebar_clip.h, 0
    #           elif text_direction == 'bottom':
    #               if ui_style == 'box':
    #                   # Anchors to the right side, leaves space on the left
    #                   start_x = final_x = self.w - sidebar_clip.w
    #                   start_y = self.h
    #                   final_y = self.h - sidebar_clip.h - box_bottom_margin
    #               else:
    #                   start_x, final_x = 0, 0
    #                   start_y, final_y = self.h, self.h - sidebar_clip.h
    #           else:
    #               # Safety fallback
    #               start_x, final_x, start_y, final_y = 0, 0, 0, 0

    #           # Determine text start time and duration based on GS transition
    #           if not has_gs_transition:
    #               text_start = video_start_time
    #               text_final_dur = text_dur
    #           else:
    #               # Start AFTER the transition has completely cleared the screen
    #               delay = max(0, trans_end_time - video_start_time)
    #               text_start = trans_end_time
    #               text_final_dur = max(0.1, text_dur - delay)

    #           sidebar_clip = sidebar_clip.with_start(text_start).with_duration(text_final_dur)

    #           # Universal slide-in animation function
    #           def slide_pos(t):
    #               if t < 0.3: 
    #                   progress = t / 0.3
    #                   x = start_x + (final_x - start_x) * progress
    #                   y = start_y + (final_y - start_y) * progress
    #                   return (int(x), int(y))
    #               else:
    #                   return (int(final_x), int(final_y))

    #           sidebar_clip = sidebar_clip.with_position(slide_pos)
    #           
    #           # Fade in effect
    #           text_effects = [vfx.CrossFadeIn(duration=0.5)]
    #           sidebar_clip = sidebar_clip.with_effects(text_effects)
    #           
    #           self.clips.append(sidebar_clip)

    #           # 7.5 Optional Logo Overlay (Top Right of the entire video)
    #           if logo_path and os.path.exists(logo_path):
    #               try:
    #                   logo_clip = ImageClip(logo_path)
    #                   # Scale logo gracefully (e.g. max 8% of screen height)
    #                   logo_h = max(30, int(self.h * 0.08))
    #                   logo_clip = logo_clip.resized(height=logo_h)
    #                   
    #                   logo_padding_x = 50
    #                   logo_padding_y = 50
    #                   logo_x = self.w - logo_clip.w - logo_padding_x
    #                   logo_y = logo_padding_y
    #                   
    #                   logo_clip = logo_clip.with_start(text_start).with_duration(text_final_dur).with_position((logo_x, logo_y))
    #                   
    #                   logo_effects = [vfx.CrossFadeIn(duration=0.5)]
    #                   logo_clip = logo_clip.with_effects(logo_effects)
    #                   
    #                   self.clips.append(logo_clip)
    #               except Exception as e:
    #                   print(f"  [ERROR] Failed to load logo '{logo_path}': {e}")

        # 8. Layer Green Screen Transition over EVERYTHING (including text and logo)
        if trans_clip:
            self.clips.append(trans_clip)

        # 9. Update Cursor
        self.current_time = video_start_time + main_clip.duration

    def render(self, output_path, fps=24):
        if not self.clips:
            print("No clips to render.")
            return

        print(f"Compositing {len(self.clips)} elements...")
        total_duration = self.current_time
        bg = ColorClip(size=(self.w, self.h), color=(0,0,0), duration=total_duration)
        final_movie = CompositeVideoClip([bg] + self.clips)
        
        print(f"Rendering full story to {output_path} (Duration: {total_duration:.2f}s)...")
        final_movie.write_videofile(
            output_path, 
            fps=fps, 
            codec='libx264', 
            audio_codec='aac',
            threads=1
        )
        print("Story render complete!")

if __name__ == "__main__":
    print("--- Starting video_editor.py test ---")
    
    # Create a test sequencer
    sequencer = StorySequencer(output_width=1080, output_height=1920)
    
    test_image = "image_input/caffetteria.png"
    
    # Create a dummy image if it doesn't exist so the test runs out of the box
    if not os.path.exists(test_image):
        import numpy as np
        import imageio
        dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        dummy_frame[:] = (40, 40, 80) # Dark blue background
        imageio.imwrite(test_image, dummy_frame)
        print(f"Created dummy image '{test_image}' for testing.")
        
    # Create a dummy sound if it doesn't exist so the test runs out of the box
    test_sound = "testing_tools/transition_sound.mp3"
    if not os.path.exists(test_sound):
        if not os.path.exists("testing_tools"):
            os.makedirs("testing_tools")
        from pydub import AudioSegment
        AudioSegment.silent(duration=1000).export(test_sound, format="mp3")
        print(f"Created dummy sound '{test_sound}' for testing.")

    # Create a dummy logo
    test_logo = "logo.png"
    if not os.path.exists(test_logo):
        import numpy as np
        import imageio
        dummy_logo = np.zeros((100, 100, 4), dtype=np.uint8)
        dummy_logo[:, :] = (255, 0, 0, 255) # Red square logo
        imageio.imwrite(test_logo, dummy_logo)
        print(f"Created dummy logo '{test_logo}' for testing.")

    print("Adding Scene 1: Box UI Style (Bottom News Ticker)...")
    sequencer.add_scene(
        video_path=None,
        title="INAUGURA LA CAFFETERIA DELLA NUOVA PIAZZA AUGUSTO IMPERATORE A ROMA. ALTRA OCCASIONE PERSA DI RISTORAZIONE MUSEALE",
        caption="Concepito come servizio museale aggiuntivo del vicino Museo dell’Ara Pacis e del complesso archeologico...",
        text_direction='bottom',
        image_path=test_image,
        ui_style='box',
        box_width_pct=0.885,       
        box_bottom_margin=35,
        logo_path=test_logo
    )

    sequencer.add_scene(
        video_path=None,
        title="INAUGURA LA CAFFETTERIA. Concepito come servizio museale aggiuntivo del vicino Museo dell’Ara Pacis e del complesso archeologico...",
        caption="Concepito come servizio museale aggiuntivo del vicino Museo dell’Ara Pacis e del complesso archeologico...",
        text_direction='bottom',
        image_path="test_bg.png",
        ui_style='box',
        box_width_pct=0.885,       
        box_bottom_margin=35, 
        transition_video_path="testing_tools/green-screen.mp4",
        transition_cut_time=0.7,
        transition_audio_path=test_sound,
        logo_path=test_logo
    )


    # Note: To test the green screen transition, you would pass:
    # transition_video_path="path/to/greenscreen.mp4", transition_cut_time=1.2 
    # to the next scene.

    if sequencer.clips:
        output_file = "test_editor_render.mp4"
        sequencer.render(output_file, fps=24)
        print(f"Test finished successfully! Check '{output_file}'.")
    else:
        print("No clips were added to the sequencer.")