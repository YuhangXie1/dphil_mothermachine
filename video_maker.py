"""
MULTI-FOV PNG IMAGE SEQUENCE -> LOSSLESS VIDEO

Expected directory structure:

    PNG_frames - auto_brightness/
        FOV_1/
            LED450NM_FOV1_frame_0000.png
            LED450NM_FOV1_frame_0001.png
            ...
        FOV_2/
            LED450NM_FOV2_frame_0000.png
            LED450NM_FOV2_frame_0001.png
            ...
        FOV_3/
            ...
        Videos/
            (videos will be written here)

The script automatically:

    1. Finds all folders named FOV_#
    2. Sorts them numerically
    3. Allows selected FOVs to be skipped
    4. Discovers the frame range separately for each FOV
    5. Optionally excludes specified frames/ranges
    6. Optionally asks for an interactive ROI for each FOV
    7. Creates one lossless FFV1 MKV video per FOV

Requirements:

    pip install opencv-python

FFmpeg must also be installed and available from the command line.
"""

from pathlib import Path
import re
import subprocess
import tempfile

import cv2


# ============================================================
# USER SETTINGS
# ============================================================

# Parent folder containing:
#
#     FOV_1/
#     FOV_2/
#     FOV_3/
#     ...
#
IMAGE_FOLDER = Path(
    r"/mnt/large_storage/shared_storage/data/Yuhang/"
    r"2026-10-12_YX001_wmmet-_exp2/Processed/PNG_frames - fixed_brightness"
)
TITLE_EXTRA = "fixed_brightness"
#TITLE_EXTRA = "auto_brightness"

# ------------------------------------------------------------
# OUTPUT
# ------------------------------------------------------------

# Generated videos will be placed in:
#
#     IMAGE_FOLDER / Videos
#
OUTPUT_FOLDER = IMAGE_FOLDER / "Videos"


# ------------------------------------------------------------
# FOV EXCLUSION
# ------------------------------------------------------------

# FOV numbers that should NOT be processed.
#
# Examples:
#
# Process everything:
#
#     FOV_EXCLUDE = []
#
# Skip FOV 2:
#
#     FOV_EXCLUDE = [2]
#
# Skip FOVs 2, 5 and 8:
#
#     FOV_EXCLUDE = [2, 5, 8]
#
FOV_EXCLUDE = []


# ------------------------------------------------------------
# VIDEO FRAME RATE
# ------------------------------------------------------------

# Playback frame rate.
#
# Lower = slower playback.
#
# Examples:
#
# FPS = 30
# FPS = 10
# FPS = 5
# FPS = 2
#
FPS = 5


# ============================================================
# FRAME EXCLUSION
# ============================================================

# Master switch for frame exclusions.
#
# False:
#     Ignore EXCLUDE_FRAMES and EXCLUDE_RANGES completely.
#     Every available PNG frame will be included.
#
# True:
#     Apply EXCLUDE_FRAMES and EXCLUDE_RANGES.
#
EXCLUDE_BOOL = False


# ------------------------------------------------------------
# INDIVIDUAL FRAME EXCLUSIONS
# ------------------------------------------------------------

# Example:
#
# EXCLUDE_FRAMES = {
#     18,
#     19,
#     24,
# }
#
EXCLUDE_FRAMES = {
    # 18,
    # 19,
    # 24,
}


# ------------------------------------------------------------
# FRAME RANGE EXCLUSIONS
# ------------------------------------------------------------

# Each tuple is inclusive at both ends.
#
# Example:
#
# EXCLUDE_RANGES = [
#     (20, 25),
#     (70, 75),
# ]
#
# removes:
#
#     20, 21, 22, 23, 24, 25
#
# and:
#
#     70, 71, 72, 73, 74, 75
#
EXCLUDE_RANGES = [
    # (20, 25),
    # (70, 75),
]


# ============================================================
# ROI SETTINGS
# ============================================================

# True:
#     For every FOV, open an image and ask you to draw
#     the region that should appear in the video.
#
# False:
#     Use the entire image.
#
USE_INTERACTIVE_ROI = False


# Which frame should be used to select the ROI?
#
# None:
#     Use the first selected frame.
#
# Or specify a frame number:
#
#     ROI_PREVIEW_FRAME = 50
#
ROI_PREVIEW_FRAME = None


# ============================================================
# VARIABLES SET AUTOMATICALLY
# ============================================================
#
# Do not normally edit these.
#
# They are changed for each FOV by main().
#

FILE_PREFIX = None

START_FRAME = None
END_FRAME = None

OUTPUT_VIDEO = None
CURRENT_FOV_FOLDER = None


# ============================================================
# FOV DISCOVERY
# ============================================================

def find_fov_folders(base_folder):
    """
    Find folders named:

        FOV_no0
        FOV_no1
        FOV_no2
        ...
        FOV_no10

    Returns:

        [
            (0, Path(.../FOV_no0)),
            (1, Path(.../FOV_no1)),
            (2, Path(.../FOV_no2)),
            ...
        ]

    sorted numerically by FOV number.
    """

    if not base_folder.exists():

        raise FileNotFoundError(
            f"Main image folder does not exist:\n"
            f"{base_folder}"
        )

    fov_folders = []

    for folder in base_folder.iterdir():

        # Ignore files.
        if not folder.is_dir():
            continue

        # Match exactly:
        #
        # FOV_no1
        # FOV_no2
        # FOV_no10
        #
        match = re.fullmatch(
            r"FOV_no(\d+)",
            folder.name,
            flags=re.IGNORECASE
        )

        if match is None:
            continue

        fov_number = int(
            match.group(1)
        )

        fov_folders.append(
            (
                fov_number,
                folder
            )
        )

    # Numerical sorting is important.
    #
    # Correct:
    #
    # FOV_no1
    # FOV_no2
    # FOV_no10
    #
    # rather than:
    #
    # FOV_no1
    # FOV_no10
    # FOV_no2
    #
    fov_folders.sort(
        key=lambda item: item[0]
    )

    return fov_folders


# ============================================================
# FRAME DISCOVERY
# ============================================================

def discover_frame_range(
    image_folder,
    file_prefix
):
    """
    Automatically discover the available frame numbers.

    For example:

        LED450NM_FOV4_frame_0000.png
        LED450NM_FOV4_frame_0001.png
        ...
        LED450NM_FOV4_frame_0135.png

    returns:

        start_frame      = 0
        end_frame        = 135
        number_of_frames = 136

    IMPORTANT:

    number_of_frames is the actual number of matching files.

    Therefore, if frame 0040 is physically missing, the count
    will reflect that.
    """

    frame_numbers = []

    pattern = re.compile(
        rf"^{re.escape(file_prefix)}(\d+)\.png$",
        flags=re.IGNORECASE
    )

    for path in image_folder.iterdir():

        if not path.is_file():
            continue

        match = pattern.match(
            path.name
        )

        if match is None:
            continue

        frame_number = int(
            match.group(1)
        )

        frame_numbers.append(
            frame_number
        )

    if not frame_numbers:

        raise RuntimeError(
            f"\nNo PNG frames found in:\n"
            f"{image_folder}\n\n"
            f"Expected filenames beginning with:\n"
            f"{file_prefix}"
        )

    frame_numbers.sort()

    start_frame = frame_numbers[0]
    end_frame = frame_numbers[-1]

    number_of_frames = len(
        frame_numbers
    )

    return (
        start_frame,
        end_frame,
        number_of_frames
    )


# ============================================================
# FRAME NUMBER
# ============================================================

def get_frame_number(path):
    """
    Extract the frame number from the current FOV's filename.

    Example:

        LED450NM_FOV4_frame_0042.png

    returns:

        42
    """

    pattern = (
        rf"^{re.escape(FILE_PREFIX)}"
        rf"(\d+)\.png$"
    )

    match = re.match(
        pattern,
        path.name,
        flags=re.IGNORECASE
    )

    if match is None:
        return None

    return int(
        match.group(1)
    )


# ============================================================
# FRAME EXCLUSIONS
# ============================================================

def build_exclusion_set():
    """
    Build the set of frames that should be excluded.

    If:

        EXCLUDE_BOOL = False

    then this function returns an empty set and ALL available
    frames are included.

    If:

        EXCLUDE_BOOL = True

    then EXCLUDE_FRAMES and EXCLUDE_RANGES are applied.
    """

    # --------------------------------------------------------
    # Exclusions globally disabled
    # --------------------------------------------------------

    if not EXCLUDE_BOOL:

        return set()

    # --------------------------------------------------------
    # Individual frames
    # --------------------------------------------------------

    excluded = set(
        EXCLUDE_FRAMES
    )

    # --------------------------------------------------------
    # Frame ranges
    # --------------------------------------------------------

    for start, end in EXCLUDE_RANGES:

        if end < start:

            raise ValueError(
                f"Invalid exclusion range: "
                f"({start}, {end})\n"
                f"The end must be >= the start."
            )

        excluded.update(
            range(
                start,
                end + 1
            )
        )

    return excluded


# ============================================================
# FIND SELECTED IMAGES
# ============================================================

def find_selected_images(
    image_folder
):
    """
    Find the PNG images that should actually appear in the
    video for the current FOV.

    Applies:

        START_FRAME
        END_FRAME

    and, when EXCLUDE_BOOL is True:

        EXCLUDE_FRAMES
        EXCLUDE_RANGES

    Returns:

        [
            (frame_number, path),
            ...
        ]

    sorted numerically.
    """

    if not image_folder.exists():

        raise FileNotFoundError(
            f"Image folder does not exist:\n"
            f"{image_folder}"
        )

    if END_FRAME < START_FRAME:

        raise ValueError(
            "END_FRAME must be >= START_FRAME."
        )

    # Empty if EXCLUDE_BOOL = False.
    excluded = build_exclusion_set()

    images = []

    for path in image_folder.iterdir():

        # Ignore directories.
        if not path.is_file():
            continue

        frame_number = get_frame_number(
            path
        )

        # Ignore unrelated files.
        if frame_number is None:
            continue

        # Ignore anything outside discovered range.
        if not (
            START_FRAME
            <= frame_number
            <= END_FRAME
        ):
            continue

        # Apply exclusions.
        #
        # If exclusions are disabled, "excluded" is empty,
        # so this never removes anything.
        if frame_number in excluded:
            continue

        images.append(
            (
                frame_number,
                path
            )
        )

    # Sort by actual frame number.
    images.sort(
        key=lambda item: item[0]
    )

    return images


# ============================================================
# READ IMAGE
# ============================================================

def read_image(path):
    """
    Read a PNG without intentionally changing its bit depth
    or number of channels.
    """

    image = cv2.imread(
        str(path),
        cv2.IMREAD_UNCHANGED
    )

    if image is None:

        raise RuntimeError(
            f"Could not read image:\n"
            f"{path}"
        )

    return image


# ============================================================
# DISPLAY IMAGE
# ============================================================

def make_roi_display_image(image):
    """
    Prepare an image for display in the ROI selection window.

    If the image is not uint8, it is converted to uint8 ONLY
    for display.

    This does NOT modify the source PNG or final video.
    """

    if image.dtype != "uint8":

        minimum = image.min()
        maximum = image.max()

        if maximum > minimum:

            display = (
                (
                    image.astype("float32")
                    - minimum
                )
                / (
                    maximum
                    - minimum
                )
                * 255
            ).astype("uint8")

        else:

            display = image.astype(
                "uint8"
            )

    else:

        display = image.copy()

    return display


# ============================================================
# INTERACTIVE ROI
# ============================================================

def select_roi_interactively(image):
    """
    Allow the user to select an ROI using the mouse.

    The preview is automatically reduced so the complete
    image fits on screen.

    The preview scaling does NOT change the final video
    resolution.

    ROI coordinates are converted back to original-image
    coordinates before being returned.

    Controls:

        Left mouse:
            Draw ROI.

        ENTER or SPACE:
            Accept.

        C:
            Cancel.
    """

    # Maximum DISPLAY size.
    #
    # This only affects the preview window.
    MAX_PREVIEW_WIDTH = 1400
    MAX_PREVIEW_HEIGHT = 850

    display = make_roi_display_image(
        image
    )

    (
        original_height,
        original_width
    ) = image.shape[:2]

    print("\n" + "=" * 60)
    print("INTERACTIVE ROI SELECTION")
    print("=" * 60)

    print(
        f"\nOriginal image resolution: "
        f"{original_width} x "
        f"{original_height}"
    )

    # --------------------------------------------------------
    # Determine preview scaling
    # --------------------------------------------------------

    width_scale = (
        MAX_PREVIEW_WIDTH
        / original_width
    )

    height_scale = (
        MAX_PREVIEW_HEIGHT
        / original_height
    )

    scale = min(
        width_scale,
        height_scale,
        1.0
    )

    # --------------------------------------------------------
    # Resize display copy if needed
    # --------------------------------------------------------

    if scale < 1.0:

        preview_width = round(
            original_width
            * scale
        )

        preview_height = round(
            original_height
            * scale
        )

        display_scaled = cv2.resize(
            display,
            (
                preview_width,
                preview_height
            ),
            interpolation=cv2.INTER_AREA
        )

        print(
            f"Preview resolution: "
            f"{preview_width} x "
            f"{preview_height}"
        )

        print(
            f"Preview scale: "
            f"{scale:.4f}"
        )

    else:

        display_scaled = display

        (
            preview_height,
            preview_width
        ) = display_scaled.shape[:2]

        print(
            "\nImage already fits "
            "inside preview window."
        )

    print(
        "\nDraw a rectangle using "
        "the LEFT MOUSE BUTTON."
    )

    print(
        "Press ENTER or SPACE to accept."
    )

    print(
        "Press C to cancel."
    )

    # --------------------------------------------------------
    # Select ROI
    # --------------------------------------------------------

    roi_scaled = cv2.selectROI(
        "Select ROI - ENTER/SPACE = Accept, C = Cancel",
        display_scaled,
        showCrosshair=True,
        fromCenter=False
    )

    cv2.destroyAllWindows()

    (
        scaled_x,
        scaled_y,
        scaled_w,
        scaled_h
    ) = [
        int(value)
        for value in roi_scaled
    ]

    # --------------------------------------------------------
    # Detect cancellation
    # --------------------------------------------------------

    if (
        scaled_w == 0
        or scaled_h == 0
    ):

        raise RuntimeError(
            "\nROI selection was cancelled "
            "or had zero width/height."
        )

    # --------------------------------------------------------
    # Convert preview coordinates back to original pixels
    # --------------------------------------------------------

    x = round(
        scaled_x / scale
    )

    y = round(
        scaled_y / scale
    )

    w = round(
        scaled_w / scale
    )

    h = round(
        scaled_h / scale
    )

    # --------------------------------------------------------
    # Keep coordinates inside image
    # --------------------------------------------------------

    x = max(
        0,
        min(
            x,
            original_width - 1
        )
    )

    y = max(
        0,
        min(
            y,
            original_height - 1
        )
    )

    w = min(
        w,
        original_width - x
    )

    h = min(
        h,
        original_height - y
    )

    if w <= 0 or h <= 0:

        raise RuntimeError(
            "Calculated ROI has zero "
            "width or height."
        )

    print("\n" + "=" * 60)
    print("ROI CONVERTED TO ORIGINAL IMAGE")
    print("=" * 60)

    print(
        f"\nX      = {x}"
    )

    print(
        f"Y      = {y}"
    )

    print(
        f"Width  = {w}"
    )

    print(
        f"Height = {h}"
    )

    print(
        f"\nFinal video resolution: "
        f"{w} x {h}"
    )

    return (
        x,
        y,
        w,
        h
    )


# ============================================================
# ROI PREVIEW
# ============================================================

def show_selected_roi_preview(
    image,
    roi
):
    """
    Display the selected ROI before creating the video.
    """

    x, y, w, h = roi

    cropped = image[
        y:y + h,
        x:x + w
    ]

    display = make_roi_display_image(
        cropped
    )

    # Make the ROI preview fit on screen too.
    max_width = 1400
    max_height = 850

    height, width = display.shape[:2]

    scale = min(
        max_width / width,
        max_height / height,
        1.0
    )

    if scale < 1.0:

        display = cv2.resize(
            display,
            (
                round(width * scale),
                round(height * scale)
            ),
            interpolation=cv2.INTER_AREA
        )

    print("\nROI PREVIEW")
    print("-" * 60)

    print(
        f"X      : {x}"
    )

    print(
        f"Y      : {y}"
    )

    print(
        f"Width  : {w}"
    )

    print(
        f"Height : {h}"
    )

    print(
        "\nPress any key in the preview "
        "window to continue."
    )

    cv2.imshow(
        "Selected ROI Preview - Press Any Key",
        display
    )

    cv2.waitKey(0)

    cv2.destroyAllWindows()


# ============================================================
# FIND ROI PREVIEW IMAGE
# ============================================================

def find_roi_preview_image(images):
    """
    Determine which frame should be displayed when selecting
    the ROI.

    ROI_PREVIEW_FRAME = None:
        use first included frame.

    Otherwise:
        search the current FOV folder for the specified frame.
    """

    if ROI_PREVIEW_FRAME is None:

        return images[0]

    for path in CURRENT_FOV_FOLDER.iterdir():

        if not path.is_file():
            continue

        frame_number = get_frame_number(
            path
        )

        if frame_number == ROI_PREVIEW_FRAME:

            return (
                frame_number,
                path
            )

    raise RuntimeError(
        f"\nROI preview frame "
        f"{ROI_PREVIEW_FRAME:04d} "
        f"could not be found in:\n"
        f"{CURRENT_FOV_FOLDER}"
    )


# ============================================================
# VALIDATE IMAGES
# ============================================================

def validate_images(images):
    """
    Verify that all images in the current sequence have the
    same:

        width
        height
        number of channels
        data type

    Video frames must be consistent.
    """

    (
        first_number,
        first_path
    ) = images[0]

    first_image = read_image(
        first_path
    )

    reference_shape = (
        first_image.shape
    )

    reference_dtype = (
        first_image.dtype
    )

    print(
        "\nChecking all selected images..."
    )

    for index, (
        frame_number,
        path
    ) in enumerate(
        images,
        start=1
    ):

        image = read_image(
            path
        )

        if image.shape != reference_shape:

            raise ValueError(
                f"\n\nImage shape mismatch "
                f"at frame {frame_number:04d}:\n\n"
                f"{path}\n\n"
                f"Expected: {reference_shape}\n"
                f"Found:    {image.shape}"
            )

        if image.dtype != reference_dtype:

            raise ValueError(
                f"\n\nImage data type mismatch "
                f"at frame {frame_number:04d}:\n\n"
                f"{path}\n\n"
                f"Expected: {reference_dtype}\n"
                f"Found:    {image.dtype}"
            )

        print(
            f"\rChecking image "
            f"{index}/{len(images)}",
            end="",
            flush=True
        )

    print(
        "\nImage check complete."
    )

    return first_image


# ============================================================
# CREATE LOSSLESS VIDEO
# ============================================================

def create_lossless_video(
    images,
    roi=None
):
    """
    Create a lossless FFV1 MKV video.

    The original PNG files are supplied directly to FFmpeg.

    If an ROI is provided, FFmpeg crops the original image
    data directly.

    There is:

        - no resizing of the video
        - no JPEG conversion
        - no H.264 compression
        - no H.265 compression

    FFV1 is a lossless video codec.
    """

    with tempfile.TemporaryDirectory() as temp_dir:

        temp_dir = Path(
            temp_dir
        )

        concat_file = (
            temp_dir
            / "frames.txt"
        )

        # ----------------------------------------------------
        # Build FFmpeg concat list
        # ----------------------------------------------------

        with open(
            concat_file,
            "w",
            encoding="utf-8"
        ) as f:

            for (
                frame_number,
                path
            ) in images:

                absolute_path = (
                    path.resolve()
                )

                # Escape single quotes for FFmpeg concat syntax.
                safe_path = str(
                    absolute_path
                ).replace(
                    "'",
                    "'\\''"
                )

                f.write(
                    f"file '{safe_path}'\n"
                )

                f.write(
                    f"duration "
                    f"{1.0 / FPS:.12f}\n"
                )

            # Repeat final file so FFmpeg respects the final
            # image duration.
            last_path = (
                images[-1][1].resolve()
            )

            safe_last_path = str(
                last_path
            ).replace(
                "'",
                "'\\''"
            )

            f.write(
                f"file '{safe_last_path}'\n"
            )

        # ----------------------------------------------------
        # FFmpeg command
        # ----------------------------------------------------

        command = [
            "ffmpeg",

            # Overwrite existing output.
            "-y",

            # Concat input.
            "-f",
            "concat",

            # Allow absolute paths.
            "-safe",
            "0",

            # Input file.
            "-i",
            str(concat_file),
        ]

        # ----------------------------------------------------
        # Optional ROI crop
        # ----------------------------------------------------

        if roi is not None:

            x, y, w, h = roi

            crop_filter = (
                f"crop="
                f"{w}:"
                f"{h}:"
                f"{x}:"
                f"{y}"
            )

            command.extend(
                [
                    "-vf",
                    crop_filter
                ]
            )

        # ----------------------------------------------------
        # Lossless output
        # ----------------------------------------------------

        command.extend(
            [
                "-r",
                str(FPS),

                "-c:v",
                "ffv1",

                "-level",
                "3",

                "-slicecrc",
                "1",

                "-f",
                "matroska",

                str(OUTPUT_VIDEO)
            ]
        )

        print("\n" + "=" * 60)
        print("CREATING VIDEO")
        print("=" * 60)

        print(
            f"\nOutput:\n"
            f"{OUTPUT_VIDEO}"
        )

        try:

            subprocess.run(
                command,
                check=True
            )

        except FileNotFoundError:

            raise RuntimeError(
                "\nFFmpeg could not be found.\n\n"
                "Make sure FFmpeg is installed and "
                "'ffmpeg' is available from the "
                "command line."
            )

        except subprocess.CalledProcessError as error:

            raise RuntimeError(
                f"\nFFmpeg failed while creating:\n"
                f"{OUTPUT_VIDEO}"
            ) from error


# ============================================================
# MAIN
# ============================================================

def main():

    global FILE_PREFIX
    global START_FRAME
    global END_FRAME
    global OUTPUT_VIDEO
    global CURRENT_FOV_FOLDER

    print("=" * 70)
    print("MULTI-FOV PNG -> LOSSLESS VIDEO")
    print("=" * 70)

    print(
        f"\nMain image folder:\n"
        f"{IMAGE_FOLDER}"
    )

    # --------------------------------------------------------
    # Discover FOVs
    # --------------------------------------------------------

    fov_folders = find_fov_folders(
        IMAGE_FOLDER
    )

    if not fov_folders:

        raise RuntimeError(
            f"\nNo FOV folders found inside:\n"
            f"{IMAGE_FOLDER}\n\n"
            f"Expected folders such as:\n"
            f"FOV_1\n"
            f"FOV_2\n"
            f"FOV_3"
        )

    discovered_fovs = [
        fov
        for fov, folder
        in fov_folders
    ]

    print(
        f"\nDiscovered "
        f"{len(fov_folders)} FOV folders."
    )

    print(
        f"FOVs found: "
        f"{discovered_fovs}"
    )

    # --------------------------------------------------------
    # FOV exclusions
    # --------------------------------------------------------

    if FOV_EXCLUDE:

        print(
            f"FOVs excluded: "
            f"{FOV_EXCLUDE}"
        )

    else:

        print(
            "FOV exclusions: NONE"
        )

    # --------------------------------------------------------
    # Frame exclusion status
    # --------------------------------------------------------

    if EXCLUDE_BOOL:

        print(
            "Frame exclusions: ENABLED"
        )

    else:

        print(
            "Frame exclusions: DISABLED"
        )

    print(
        f"Video FPS: {FPS}"
    )

    # --------------------------------------------------------
    # Output folder
    # --------------------------------------------------------

    OUTPUT_FOLDER.mkdir(
        parents=True,
        exist_ok=True
    )

    print(
        f"\nVideos will be saved to:\n"
        f"{OUTPUT_FOLDER}"
    )

    # ========================================================
    # PROCESS EACH FOV
    # ========================================================

    processed_count = 0

    for fov, fov_folder in fov_folders:

        # ----------------------------------------------------
        # Skip excluded FOVs
        # ----------------------------------------------------

        if fov in FOV_EXCLUDE:

            print(
                f"\nSkipping FOV {fov}."
            )

            continue

        print("\n\n")
        print("#" * 70)
        print(f"PROCESSING FOV {fov}")
        print("#" * 70)

        print(
            f"\nInput folder:\n"
            f"{fov_folder}"
        )

        # ----------------------------------------------------
        # Set variables for current FOV
        # ----------------------------------------------------

        CURRENT_FOV_FOLDER = (
            fov_folder
        )

        FILE_PREFIX = (
            f"LED450NM_FOV{fov}_frame_"
        )

        # Fresh output path for every FOV.
        OUTPUT_VIDEO = (
            OUTPUT_FOLDER
            / f"LED450NM_FOV{fov}_video_{TITLE_EXTRA}.mkv"
        )

        # ----------------------------------------------------
        # Automatically discover frame range
        # ----------------------------------------------------

        (
            START_FRAME,
            END_FRAME,
            num_frames
        ) = discover_frame_range(
            fov_folder,
            FILE_PREFIX
        )

        print(
            f"\nDiscovered PNG files: "
            f"{num_frames}"
        )

        print(
            f"Available frame range: "
            f"{START_FRAME:04d} -> "
            f"{END_FRAME:04d}"
        )

        # ----------------------------------------------------
        # Select frames
        # ----------------------------------------------------

        images = find_selected_images(
            fov_folder
        )

        if not images:

            print(
                f"\nWARNING: No usable frames "
                f"remain for FOV {fov}."
            )

            print(
                "Skipping this FOV."
            )

            continue

        # ----------------------------------------------------
        # Report exclusions
        # ----------------------------------------------------

        if EXCLUDE_BOOL:

            excluded = (
                build_exclusion_set()
            )

            excluded_in_range = sorted(
                frame
                for frame in excluded
                if (
                    START_FRAME
                    <= frame
                    <= END_FRAME
                )
            )

            print(
                "\nFrame exclusion: ENABLED"
            )

            if excluded_in_range:

                print(
                    f"Excluded frames:\n"
                    f"{excluded_in_range}"
                )

            else:

                print(
                    "No excluded frames occur "
                    "within this FOV's range."
                )

        else:

            print(
                "\nFrame exclusion: DISABLED"
            )

            print(
                "All available frames will be used."
            )

        # ----------------------------------------------------
        # Report actual video frames
        # ----------------------------------------------------

        print(
            f"\nFrames going into video: "
            f"{len(images)}"
        )

        print(
            f"First included frame: "
            f"{images[0][0]:04d}"
        )

        print(
            f"Last included frame: "
            f"{images[-1][0]:04d}"
        )

        # ----------------------------------------------------
        # Validate sequence
        # ----------------------------------------------------

        first_image = validate_images(
            images
        )

        (
            height,
            width
        ) = first_image.shape[:2]

        print(
            f"\nSource resolution: "
            f"{width} x {height}"
        )

        print(
            f"Data type: "
            f"{first_image.dtype}"
        )

        if first_image.ndim == 2:

            print(
                "Channels: 1"
            )

        else:

            print(
                f"Channels: "
                f"{first_image.shape[2]}"
            )

        # ====================================================
        # ROI
        # ====================================================

        roi = None

        if USE_INTERACTIVE_ROI:

            (
                preview_frame_number,
                preview_path
            ) = find_roi_preview_image(
                images
            )

            print(
                f"\nUsing frame "
                f"{preview_frame_number:04d} "
                f"for FOV {fov} ROI selection."
            )

            print(
                f"Preview image:\n"
                f"{preview_path}"
            )

            preview_image = read_image(
                preview_path
            )

            roi = select_roi_interactively(
                preview_image
            )

            x, y, w, h = roi

            print("\nSelected ROI:")

            print(
                f"X      = {x}"
            )

            print(
                f"Y      = {y}"
            )

            print(
                f"Width  = {w}"
            )

            print(
                f"Height = {h}"
            )

            print(
                f"Video resolution: "
                f"{w} x {h}"
            )

            show_selected_roi_preview(
                preview_image,
                roi
            )

        else:

            print(
                "\nInteractive ROI disabled."
            )

            print(
                "Using complete image."
            )

            print(
                f"Video resolution: "
                f"{width} x {height}"
            )

        # ====================================================
        # CREATE VIDEO
        # ====================================================

        print(
            f"\nCreating video "
            f"for FOV {fov}..."
        )

        create_lossless_video(
            images,
            roi
        )

        processed_count += 1

        # ----------------------------------------------------
        # Report completion
        # ----------------------------------------------------

        duration = (
            len(images)
            / FPS
        )

        print("\n" + "-" * 70)

        print(
            f"FOV {fov} COMPLETE"
        )

        print(
            f"\nVideo:\n"
            f"{OUTPUT_VIDEO}"
        )

        print(
            f"\nFrames: "
            f"{len(images)}"
        )

        print(
            f"FPS: "
            f"{FPS}"
        )

        print(
            f"Approximate duration: "
            f"{duration:.2f} seconds"
        )

        if roi is not None:

            x, y, w, h = roi

            print(
                f"ROI: "
                f"x={x}, "
                f"y={y}, "
                f"w={w}, "
                f"h={h}"
            )

        print("-" * 70)

    # ========================================================
    # EVERYTHING FINISHED
    # ========================================================

    print("\n\n")
    print("=" * 70)
    print("ALL FOVs COMPLETE")
    print("=" * 70)

    print(
        f"\nVideos created: "
        f"{processed_count}"
    )

    print(
        f"\nVideos saved in:\n"
        f"{OUTPUT_FOLDER}"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()