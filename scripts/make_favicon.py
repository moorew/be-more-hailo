from PIL import Image
import os

def create_favicon():
    img_path = 'faces/idle/0001.png'
    if not os.path.exists(img_path):
        print(f"Could not find {img_path}")
        return

    print(f"Opening {img_path}...")
    img = Image.open(img_path)
    
    # Calculate crop box to make it square (centered)
    width, height = img.size
    size = min(width, height)
    left = (width - size) / 2
    top = (height - size) / 2
    right = (width + size) / 2
    bottom = (height + size) / 2
    
    # Crop and resize to 512x512
    img_cropped = img.crop((left, top, right, bottom))
    img_resized = img_cropped.resize((512, 512), Image.Resampling.LANCZOS)
    
    # Save as favicon.png in static folder
    os.makedirs('static', exist_ok=True)
    save_path = 'static/favicon.png'
    img_resized.save(save_path)
    print(f"Favicon created successfully at {save_path}")

if __name__ == "__main__":
    create_favicon()
