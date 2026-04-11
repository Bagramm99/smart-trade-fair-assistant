import os
import time
from openai import OpenAI
from pypepper import PepperRobot
from dotenv import load_dotenv

# -------------------------------
# OpenAI key aus .env oder Shell
# -------------------------------
load_dotenv()
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_KEY:
    raise ValueError("Set your OPENAI_API_KEY in .env or shell environment!")

# OpenAI-Client initialisieren
client = OpenAI(api_key=OPENAI_KEY)

# -------------------------------
# Pepper sprechen lassen
# -------------------------------
def pepper_say(pepper, text):
    print("Pepper:", text)
    pepper.say(text)

# -------------------------------
#  Yes/No Listener mit Pepper ALSpeechRecognition
# -------------------------------
def pepper_listen_yes_no(pepper, timeout=6):
    recognizer_name = "WordRecognition"
    try:
        asr = pepper.session.service("ALSpeechRecognition")
        memory = pepper.session.service("ALMemory")

        # vorherige Subscription abmelden
        try:
            asr.unsubscribe(recognizer_name)
        except:
            pass

        memory.insertData("WordRecognized", [])
        asr.setLanguage("English")
        asr.pause(True)
        asr.setVocabulary(["yes", "no"], False)
        asr.pause(False)
        asr.subscribe(recognizer_name)

        start = time.time()
        while time.time() - start < timeout:
            data = memory.getData("WordRecognized")
            if isinstance(data, list) and len(data) >= 2:
                word = str(data[0]).lower().strip()
                confidence = float(data[1])
                if confidence > 0.35 and word in ["yes", "no"]:
                    asr.unsubscribe(recognizer_name)
                    return word
            time.sleep(0.2)

        asr.unsubscribe(recognizer_name)
        return None

    except Exception as e:
        print("Listen error:", e)
        try:
            asr.unsubscribe(recognizer_name)
        except:
            pass
        return None

# -------------------------------
#  LLM helper
# -------------------------------
def ask_llm(prompt, model="gpt-4o-mini"):
    response = client.responses.create(model=model, input=prompt)
    return response.output_text.strip()

# -------------------------------
# Temi Simulation
# -------------------------------
def temi_show(screen):
    print(f" Temi shows: {screen}")

def temi_deliver_flyer(topic):
    print(f" Temi delivers flyer: {topic}")
    time.sleep(1)

# -------------------------------
#  Main Scenario
# -------------------------------
def main():
    PEPPER_IP = "172.30.36.41"
    with PepperRobot(PEPPER_IP) as pepper:
        pepper.wakeup()
        pepper.go_to_posture("Stand")

        # START
        pepper_say(pepper, "Hello! Welcome to the International Student Office. How can I help you today?")
        temi_show("welcome")

        # Visitor asks about Erasmus
        visitor_question_1 = "How can I study abroad with Erasmus?"
        print("Visitor:", visitor_question_1)
        erasmus_answer = ask_llm("Explain Erasmus+ briefly in 2 sentences for a student.")
        temi_show("erasmus")
        pepper_say(pepper, erasmus_answer)

        # Flyer interaction
        pepper_say(pepper, "Would you like me to ask Temi to bring you an Erasmus flyer?")
        answer = pepper_listen_yes_no(pepper)
        if answer == "yes":
            temi_deliver_flyer("erasmus")
            pepper_say(pepper, "Here you go! ")
        else:
            pepper_say(pepper, "No problem!")

        # Health insurance
        visitor_question_2 = "Do I need health insurance?"
        print("Visitor:", visitor_question_2)
        insurance_answer = ask_llm("Explain health insurance for international students in Germany in 2 sentences.")
        temi_show("health_insurance")
        pepper_say(pepper, insurance_answer)

        # Goodbye
        visitor_question_3 = "Thanks, bye!"
        print("Visitor:", visitor_question_3)
        pepper_say(pepper, "You're very welcome! Have a great day!")
        temi_show("farewell")

        pepper.rest()

# -------------------------------
if __name__ == "__main__":
    main()