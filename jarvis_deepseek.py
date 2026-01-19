import os
import time
import threading
import queue
import subprocess
import json
import webbrowser
import re
import requests
import pyautogui
import psutil
from gtts import gTTS
from playsound import playsound
import speech_recognition as sr
import pyttsx3
from tempfile import NamedTemporaryFile

# ---------------- CONFIGURATION ----------------
DEEPSEEK_API_KEY = "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"


recognizer = sr.Recognizer()
mic = sr.Microphone()
tts_engine = None
cmd_queue = queue.Queue()


# ---------------- HELPER FUNCTIONS ----------------
def initialize_tts():
    global tts_engine
    try:
        tts_engine = pyttsx3.init()
    except Exception as e:
        print(f"Failed to initialize TTS engine: {e}")
        tts_engine = None


def speak_text(text, lang_hint="en"):
    if not text.strip():
        return
    try:
        gtts_lang = "zh-cn" if lang_hint in ("zh", "zh-cn") else lang_hint
        with NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_audio:
            tts = gTTS(text=text, lang=gtts_lang, slow=False)
            tts.save(tmp_audio.name)
            tmp_audio_path = tmp_audio.name
        playsound(tmp_audio_path)
        # Clean up the temporary file
        try:
            os.remove(tmp_audio_path)
        except:
            pass
    except Exception as e:
        print("gTTS failed, using pyttsx3:", e)
        if tts_engine:
            try:
                tts_engine.say(text)
                tts_engine.runAndWait()
            except Exception as tts_error:
                print(f"TTS engine error: {tts_error}")


def safe_run_system_command(cmd):
    dangerous = ["format", "rm -rf", "del ", "shutdown", "reboot", "restart", "poweroff"]
    if any(word in cmd.lower() for word in dangerous):
        speak_text("This command is dangerous. Type CONFIRM to proceed.")
        confirm = input("Type CONFIRM to run dangerous command: ").strip()
        if confirm != "CONFIRM":
            return "Cancelled."
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return result.stdout or result.stderr or "Command executed."
    except Exception as e:
        return f"Error: {e}"


def deepseek_chat(user_input, system_prompt=""):
    if not DEEPSEEK_API_KEY:
        return "DeepSeek API key not configured."

    # Updated API endpoint and model name
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ],
        "max_tokens": 1000,
        "temperature": 0.7
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data['choices'][0]['message']['content']
    except requests.exceptions.ConnectionError as e:
        print("Network connection error:", e)
        return "Sorry, I could not connect to the internet. Please check your connection."
    except requests.exceptions.Timeout as e:
        print("Request timeout:", e)
        return "Sorry, the request timed out. Please try again."
    except Exception as e:
        print("DeepSeek API error:", e)
        return "Sorry, I could not reach DeepSeek."


# ---------------- COMMAND HANDLING ----------------
def handle_command_text(cmd_text):
    lowered = cmd_text.lower()

    # Open website/file
    if lowered.startswith("open "):
        target = cmd_text[len("open "):].strip()
        speak_text(f"Opening {target}")
        if os.path.exists(target):
            os.startfile(target) if os.name == "nt" else subprocess.run(["xdg-open", target])
        else:
            webbrowser.open(target)
        return f"Opened {target}"

    # Google search
    if lowered.startswith("search ") or lowered.startswith("google "):
        query = cmd_text.split(" ", 1)[1]
        url = f"https://www.google.com/search?q={requests.utils.requote_uri(query)}"
        webbrowser.open(url)
        return f"Searched Google for: {query}"

    # Screenshot
    if "screenshot" in lowered:
        filename = f"screenshot_{int(time.time())}.png"
        pyautogui.screenshot().save(filename)
        speak_text(f"Screenshot saved as {filename}")
        return f"Screenshot saved: {filename}"

    # Volume control
    if "volume up" in lowered:
        pyautogui.press("volumeup")
        return "Volume increased."
    if "volume down" in lowered:
        pyautogui.press("volumedown")
        return "Volume decreased."

    # Run shell
    if lowered.startswith("run "):
        return safe_run_system_command(cmd_text.split(" ", 1)[1])

    # System stats
    if "cpu" in lowered and "usage" in lowered:
        txt = f"CPU usage: {psutil.cpu_percent(interval=1)}%"
        speak_text(txt)
        return txt
    if "memory" in lowered:
        mem = psutil.virtual_memory()
        txt = f"Memory: {mem.percent}% used, {round(mem.available / 1024 / 1024)} MB available"
        speak_text(txt)
        return txt
    if "battery" in lowered:
        try:
            bat = psutil.sensors_battery()
            txt = f"Battery: {bat.percent}%, Charging: {bat.power_plugged}" if bat else "Battery info unavailable"
        except:
            txt = "Battery info unavailable"
        speak_text(txt)
        return txt

    # Weather
    if "weather" in lowered:
        city = "New Delhi"
        match = re.search(r"in (.+)", lowered)
        if match:
            city = match.group(1)
        if OPENWEATHER_API_KEY:
            try:
                url = f"http://api.openweathermap.org/data/2.5/weather?q={requests.utils.requote_uri(city)}&appid={OPENWEATHER_API_KEY}&units=metric"
                r = requests.get(url, timeout=10).json()
                txt = f"Weather in {city}: {r['main']['temp']}°C, {r['weather'][0]['description']}"
                speak_text(txt)
                return txt
            except:
                return "Could not fetch weather."
        return "Weather API key not set."

    # Fallback: DeepSeek conversation
    system_prompt = "You are a desktop assistant. Answer user questions or suggest actions."
    reply = deepseek_chat(cmd_text, system_prompt)
    speak_text(reply)
    return reply


# ---------------- LISTENER ----------------
def listen_for_wake_and_command():
    with mic as source:
        recognizer.adjust_for_ambient_noise(source, duration=1)
        print("Listening for 'Jarvis'...")
        while True:
            try:
                audio = recognizer.listen(source, timeout=None, phrase_time_limit=8)
                text = recognizer.recognize_google(audio).strip()
                lowered = text.lower()
                if "jarvis" in lowered:
                    idx = lowered.find("jarvis")
                    cmd = text[idx + len("jarvis"):].strip()
                    if not cmd:
                        speak_text("Yes? What can I do?")
                        continue
                    cmd_queue.put(cmd)
                else:
                    cmd_queue.put(text)
            except sr.UnknownValueError:
                continue
            except Exception as e:
                print("Mic error:", e)
                time.sleep(1)


# ---------------- WORKER ----------------
def worker_loop():
    while True:
        cmd = cmd_queue.get()
        if cmd is None:
            break
        print("Processing:", cmd)
        result = handle_command_text(cmd)
        print("Result:", result)
        cmd_queue.task_done()


# ---------------- MAIN ----------------
def main():
    # Initialize TTS engine
    initialize_tts()

    speak_text("Hello, I am Jarvis.")

    # Start background threads
    threading.Thread(target=listen_for_wake_and_command, daemon=True).start()
    threading.Thread(target=worker_loop, daemon=True).start()

    speak_text("Jarvis online. Say 'Jarvis' followed by a command or type below.")

    try:
        while True:
            typed = input("You: ").strip()
            if typed.lower() in ("exit", "quit"):
                cmd_queue.put(None)
                break
            if typed:
                cmd_queue.put(typed)
            time.sleep(0.2)
    except KeyboardInterrupt:
        cmd_queue.put(None)
    finally:
        # Clean up TTS engine
        if tts_engine:
            try:
                tts_engine.stop()
            except:
                pass


if __name__ == "__main__":
    main()
