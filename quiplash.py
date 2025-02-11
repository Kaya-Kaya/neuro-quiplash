from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, ElementNotInteractableException, NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import random

import os
import sys
import traceback

import trio
from libcomponent.component import Event, ExternalRaiseManager

from neuro_api.command import Action
from neuro_api.event import NeuroAPIComponent

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup


async def run():
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

        await manager.raise_event(Event("connect", url))
        await trio.sleep(0.01)

        if neuro_component.not_connected:
            return
        
        await neuro_component.send_startup_command()

        roomcode = input("Enter room code: ")

        async def set_name(
            name: str,
        ) -> tuple[bool, str | None]:
            print(f"{name = }")
            return (len(name) < 10), f"{name = }"

        await neuro_component.register_temporary_actions(
            (
                (
                    Action(
                        "set_name",
                        "Sets your name. Cannot be longer than 10 characters.",
                        {"type": "string"},
                    ),
                    set_name,
                ),
            ),
        )
        await neuro_component.send_force_action(
            "state",
            "query",
            ["set_name"],
        )

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
                state_answer_question = driver.find_element(By.ID, "state-answer-question")

                if "pt-page-off" not in state_answer_question.get_attribute("class"):
                    question = state_answer_question.find_element(By.ID, "question-text").text

                    answer = ai.respond_no_memory(question)

                    answer_box = WebDriverWait(state_answer_question, 10).until(
                        EC.presence_of_element_located((By.ID, "quiplash-answer-input"))
                    )
                    answer_box.send_keys(answer)

                    submit_button = WebDriverWait(state_answer_question, 10).until(
                        EC.element_to_be_clickable((By.ID, "quiplash-submit-answer"))
                    )
                    submit_button.click()
                    trio.sleep(1)
                    continue        

                state_vote = driver.find_element(By.ID, "state-vote")

                if "pt-page-off" not in state_vote.get_attribute("class"):
                    trio.sleep(1)
                    vote_text = state_vote.find_element(By.ID, "vote-text").text

                    if vote_text != "Wait for the other players!":
                        # question_text = state_vote.find_element(By.ID, "question-text").text

                        vote_buttons = WebDriverWait(state_vote, 10).until(
                            EC.presence_of_all_elements_located((By.CLASS_NAME, "quiplash2-vote-button"))
                        )
                        if len(vote_buttons) > 0:
                            vote_button = random.choice(vote_buttons)
                            vote_button.click()
                            trio.sleep(1)
                            continue
            except KeyboardInterrupt:
                driver.quit()
                await neuro_component.stop()
                return
            except (NoSuchElementException, TimeoutException, ElementNotInteractableException):
                pass

if __name__ == "__main__":
    try:
        trio.run()
    except ExceptionGroup as exc:
        traceback.print_exception(exc)