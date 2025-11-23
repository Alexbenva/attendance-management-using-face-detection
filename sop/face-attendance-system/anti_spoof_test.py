"""
Anti-spoofing liveness detection module (V6 - with UI Feedback)
"""

import cv2
import time
import numpy as np
import face_recognition

SHOW_DEBUG_IMAGES = True
LIVENESS_THRESHOLD_LOW = 1.5
LIVENESS_THRESHOLD_HIGH = 25.0

def update_ui_feedback(label, message, color):
    """Helper function to update the UI label safely."""
    label.config(text=message, fg=color)
    label.winfo_toplevel().update_idletasks() # Force immediate UI update

def get_live_frame(camera_object):
    """Grabs multiple frames to clear the buffer and returns the latest one."""
    for _ in range(5):
        camera_object.grab()
    ret, frame = camera_object.read()
    if not ret: return None
    return cv2.flip(frame, 1)

def test_from_frames(frame1, frame2, face_location):
    """Compares the face region between two frames."""
    top, right, bottom, left = face_location
    face1_roi = frame1[top:bottom, left:right]
    face2_roi = frame2[top:bottom, left:right]

    if face1_roi.size == 0 or face2_roi.size == 0:
        return 0, "Error: Face crop failed"

    gray_face1 = cv2.cvtColor(face1_roi, cv2.COLOR_BGR2GRAY)
    gray_face2 = cv2.cvtColor(face2_roi, cv2.COLOR_BGR2GRAY)
    mad = np.mean(np.abs(gray_face1.astype(np.float32) - gray_face2.astype(np.float32)))
    
    if mad < LIVENESS_THRESHOLD_LOW:
        reason = "Too Still (Potential Photo)"
        success = False
    elif mad > LIVENESS_THRESHOLD_HIGH:
        reason = "Too Much Movement"
        success = False
    else:
        reason = "Live"
        success = True
        
    print(f"[Liveness INFO] Score (MAD) = {mad:.2f} | Result: {reason}")
    return (1 if success else 0), reason

def test(camera_object, ui_feedback_label):
    """
    Self-contained liveness procedure that provides real-time feedback to the UI.
    """
    if not camera_object or not camera_object.isOpened():
        update_ui_feedback(ui_feedback_label, "Camera Error!", "red")
        return 0, None

    # --- Step 1: Initial Capture ---
    update_ui_feedback(ui_feedback_label, "Get Ready...\nHOLD STILL", "cyan")
    time.sleep(1.5)
    f1 = get_live_frame(camera_object)
    if f1 is None:
        update_ui_feedback(ui_feedback_label, "Frame 1 Capture Failed", "red")
        return 0, None
    
    faces = face_recognition.face_locations(f1)
    if not faces:
        update_ui_feedback(ui_feedback_label, "No face detected.\nPlease position your face in the center.", "red")
        return 0, None
    face_location = faces[0]

    # --- Step 2: Movement Capture ---
    update_ui_feedback(ui_feedback_label, ">>> NOW, MOVE YOUR\nHEAD SLOWLY <<<", "yellow")
    time.sleep(1.5)
    f2 = get_live_frame(camera_object)
    if f2 is None:
        update_ui_feedback(ui_feedback_label, "Frame 2 Capture Failed", "red")
        return 0, None

    # --- Step 3: Analysis ---
    update_ui_feedback(ui_feedback_label, "Analyzing...", "cyan")
    time.sleep(0.5)
    result, reason = test_from_frames(f1, f2, face_location)

    if result == 1:
        update_ui_feedback(ui_feedback_label, "Liveness Check Passed!", "green")
        time.sleep(1)
    else:
        update_ui_feedback(ui_feedback_label, f"Liveness Failed:\n{reason}", "red")
        if SHOW_DEBUG_IMAGES:
            top, right, bottom, left = face_location
            cv2.rectangle(f1, (left, top), (right, bottom), (0, 255, 0), 2)
            cv2.rectangle(f2, (left, top), (right, bottom), (0, 0, 255), 2)
            debug_img = np.hstack((f1, f2))
            cv2.imshow(f"Liveness Debug: {reason}", debug_img)
            cv2.waitKey(4000)
            try: cv2.destroyWindow(f"Liveness Debug: {reason}")
            except: pass

    return result, f2