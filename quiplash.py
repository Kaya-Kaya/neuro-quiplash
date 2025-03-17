from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, ElementNotInteractableException, NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import os
import sys
import traceback

import trio
from libcomponent.component import Event, ExternalRaiseManager

from neuro_api.command import Action
from neuro_api.event import NeuroAPIComponent
from neuro_api.api import NeuroAction

import json

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

MAX_NAME_LENGTH = 12
MAX_ANSWER_LENGTH = 45

async def run() -> None:
    url = "https://jackbox.tv/"
    websocket_url = os.environ.get("NEURO_SDK_WS_URL", "ws://localhost:8000")

    async with trio.open_nursery(strict_exception_groups=True) as nursery:
        manager = ExternalRaiseManager("name", nursery)

        neuro_component = NeuroAPIComponent("neuro_api", "Quiplash 2")
        manager.add_component(neuro_component)

        neuro_component.register_handler(
            "connect",
            neuro_component.handle_connect,
        )

        await manager.raise_event(Event("connect", websocket_url))
        await trio.sleep(0.01)

        if neuro_component.not_connected:
            print("Neuro not connected, stopping.")
            await neuro_component.stop()
            return
        
        await neuro_component.send_startup_command()

        neuro_played = trio.Event()

        roomcode = input("Enter room code: ")
        assert len(roomcode) == 4, "Room code must be 4 letters."

        username = ""
        response = ""
        vote = -1
        vote_option_count = 0

        async def set_name_action(
            action: NeuroAction,
        ) -> tuple[bool, str | None]:
            try:
                data = json.loads(action.data)
            except:
                return False, "Invalid JSON, failed to unpack."
            
            if "name" not in data:
                return False, "Data must contain field 'name'."
            
            if (len(data["name"]) == 0):
                return False, "Received blank name. Must enter in a name."
            elif (len(data["name"]) <= MAX_NAME_LENGTH):
                nonlocal username
                username = data["name"]
                neuro_played.set()
                
                return True, f"{data["name"] = }"
            else:
                return False, f"Received {len(data["name"])} character name. Name cannot exceed {MAX_NAME_LENGTH} characters."
            
        async def answer_action(
            action: NeuroAction
        ) -> tuple[bool, str | None]:
            try:
                data = json.loads(action.data)
            except:
                return False, "Invalid JSON, failed to unpack."
            
            if "answer" not in data:
                return False, "Data must contain field 'answer'."
            
            if (len(data["answer"]) == 0):
                return False, "Received blank answer. Must enter in an answer."
            elif (len(data["answer"]) <= MAX_ANSWER_LENGTH):
                nonlocal response
                response = data["answer"]
                neuro_played.set()

                return True, f"{data["answer"] = }"
            else:
                return False, f"Received {len(data["answer"])} answer. Answer cannot exceed {MAX_ANSWER_LENGTH} characters."
            
        async def vote_action(
            action: NeuroAction
        ) -> tuple[bool, str | None]:
            try:
                data = json.loads(action.data)
            except:
                return False, "Invalid JSON, failed to unpack." 
            
            if "vote" not in data:
                return False, "Data must contain field 'vote'."
            
            try:
                choice = int(data["vote"])
            except:
                return False, "'vote' must be an integer."
            
            if choice <= 0 or choice > vote_option_count:
                return False, f"Invalid choice. Choices are from 1 to {vote_option_count}, inclusive."
            else:
                nonlocal vote
                vote = choice - 1
                neuro_played.set()

                return True, f"{vote = }"

        await neuro_component.register_temporary_actions(
            (
                (
                    Action(
                        "set_name",
                        f"Sets your name. Cannot be longer than {MAX_NAME_LENGTH} characters.",
                        {
                            "type": "object",
                            "required": ["name"],
                            "properties": {
                                "name": { "type": "string" }
                            }
                        },
                    ),
                    set_name_action,
                ),
            ),
        )
        await neuro_component.send_force_action(
            "You're starting a game of Quiplash.",
            "Choose your name.",
            ["set_name"],
        )

        await neuro_played.wait()
        neuro_played = trio.Event()

        driver = webdriver.Chrome()

        # Open the website
        driver.get(url)

        try:
            roomcode_box = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, 'roomcode'))
            )
            roomcode_box.send_keys(roomcode)

            name_box = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, 'username'))
            )
            name_box.send_keys(username)

            play_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, 'button-join'))
            )
            play_button.click()
        except Exception as e:
            print(f"An error occurred: {e}")
            driver.quit()
            await neuro_component.stop()
            return

        while True:
            try:
                # Answering prompt

                state_answer_question = driver.find_element(By.ID, "state-answer-question")

                if "pt-page-off" not in state_answer_question.get_attribute("class"):
                    await trio.sleep(0.1)
                    question = state_answer_question.find_element(By.ID, "question-text").text

                    await neuro_component.register_temporary_actions(
                        (
                            (
                                Action(
                                    "respond",
                                    f"Responds with your answer to the prompt. Cannot be longer than {MAX_ANSWER_LENGTH} characters.",
                                    {
                                        "type": "object",
                                        "required": ["answer"],
                                        "properties": {
                                            "answer": { "type": "string" }
                                        }
                                    },
                                ),
                                answer_action,
                            ),
                        ),
                    )
                    await neuro_component.send_force_action(
                        f"Prompt: {question}",
                        "Write a response to the given prompt.",
                        ["respond"],
                    )

                    await neuro_played.wait()
                    neuro_played = trio.Event()

                    answer_box = WebDriverWait(state_answer_question, 10).until(
                        EC.presence_of_element_located((By.ID, "quiplash-answer-input"))
                    )
                    answer_box.send_keys(response)

                    submit_button = WebDriverWait(state_answer_question, 10).until(
                        EC.element_to_be_clickable((By.ID, "quiplash-submit-answer"))
                    )
                    submit_button.click()
                    await trio.sleep(1)
                    continue        
                
                # Voting

                state_vote = driver.find_element(By.ID, "state-vote")

                if "pt-page-off" not in state_vote.get_attribute("class"):
                    await trio.sleep(1)
                    vote_text = state_vote.find_element(By.ID, "vote-text").text

                    if vote_text != "Wait for the other players!":
                        question_text = state_vote.find_element(By.ID, "question-text").text

                        vote_buttons = WebDriverWait(state_vote, 10).until(
                            EC.presence_of_all_elements_located((By.CLASS_NAME, "quiplash2-vote-button"))
                        )

                        if len(vote_buttons) > 0:
                            answers = [f"{i + 1}: {button.text}" for i, button in enumerate(vote_buttons)]
                            answers_str = "\n".join(answers)

                            vote_option_count = len(answers)
                            
                            await neuro_component.register_temporary_actions(
                                (
                                    (
                                        Action(
                                            "cast_vote",
                                            "Votes for the best answer to the prompt. Provide the index of your favorite answer.",
                                            {
                                                "type": "object",
                                                "required": ["vote"],
                                                "properties": {
                                                    "vote": { "type": "integer" }
                                                }
                                            },
                                        ),
                                        vote_action,
                                    ),
                                ),
                            )
                            await neuro_component.send_force_action(
                                "You're voting on your favorite answer to the prompt.",
                                f"Prompt: {question_text}\nAnswers:\n{answers_str}",
                                ["cast_vote"],
                            )

                            await neuro_played.wait()
                            neuro_played = trio.Event() 

                            vote_button = vote_buttons[vote]
                            vote_button.click()
                            await trio.sleep(1)
                            continue
            except KeyboardInterrupt:
                driver.quit()
                await neuro_component.stop()
                return
            except (NoSuchElementException, TimeoutException, ElementNotInteractableException):
                pass

if __name__ == "__main__":
    try:
        trio.run(run)
    except ExceptionGroup as exc:
        traceback.print_exception(exc)