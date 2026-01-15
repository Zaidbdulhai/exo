import requests
import time
import sys

# Wir nehmen das kleinste Modell (Llama-3.2-1B), das geht am schnellsten!
MODEL_NAME = "llama-3.2-1b"

print(f"1. Klopfe beim Chef an und bestelle: {MODEL_NAME} ...")

url = "http://127.0.0.1:52415/v1/chat/completions"
payload = {
    "model": MODEL_NAME,
    "messages": [{"role": "user", "content": "Sag einfach nur: Hallo Meister!"}],
    "temperature": 0.7
}

try:
    print("2. Warte auf Antwort... (Das kann beim ersten Mal 2-3 Minuten dauern!)")
    print("   SCHAU JETZT IN DAS ANDERE SCHWARZE FENSTER (SERVER)!")
    
    # Wir geben ihm 10 Minuten Zeit zum Laden
    response = requests.post(url, json=payload, timeout=600)

    if response.status_code == 200:
        print("\n🎉 JAAA! ES HAT GEKLAPPT!")
        print("Antwort:", response.json()['choices'][0]['message']['content'])
    else:
        print(f"\n❌ Der Server hat abgelehnt (Code {response.status_code}).")
        print("Grund:", response.text)
        
except Exception as e:
    print(f"\n❌ Fehler: {e}")

input("\nDrücke Enter zum Beenden...")