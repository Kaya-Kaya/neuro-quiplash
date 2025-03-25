"""
Example Game - NeuroQuiplash
This module implements asynchronous interactions for a game using Selenium 
(web browser automation), the Trio async library, and the Neuro API.
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, ElementNotInteractableException, NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import os
import sys
import traceback
import logging
from typing import Optional, Callable, Tuple, Any, Coroutine

import trio
from libcomponent.component import Event, ExternalRaiseManager

from neuro_api.command import Action
from neuro_api.event import NeuroAPIComponent
from neuro_api.api import NeuroAction

import json

# For compatibility with Python versions below 3.11, use the backported ExceptionGroup
if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

# Define configuration constants
MAX_NAME_LENGTH = 12
MAX_ANSWER_LENGTH = 45
BASE_URL = "https://jackbox.tv/"
WEBSOCKET_ENV_VAR = "NEURO_SDK_WS_URL"
WEBDRIVER_TIMEOUT = 10
PAUSE_TIME = 1
WEBSOCKET_CONNECTION_WAIT_TIME = 0.05
ANSWER_WAIT = 0.1
ROOMCODE_LENGTH = 4

# Configure logging for this module
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class GameState:
    """Encapsulate all game state variables and provide methods for state management."""
    def __init__(self):
        self.username: Optional[str] = None  # Player's chosen name
        self.response: Optional[str] = None  # Player's submitted answer
        self.vote: int = -1  # The index corresponding to the player's vote
        self.vote_option_count: int = 0  # How many answer options are available for voting
        self.played = trio.Event()  # Event to signal when an action (name setting, answer, vote) is complete

    def reset_played(self) -> None:
        """Reset the 'played' event so it can be used for the next game action."""
        self.played = trio.Event()

def handle_json(
    action_function: Callable[[dict, GameState], Coroutine[Any, Any, Tuple[bool, Optional[str]]]]
) -> Callable[[NeuroAction, GameState], Coroutine[Any, Any, Tuple[bool, Optional[str]]]]:
    """
    Decorator that parses JSON data from the NeuroAction and calls the specified action function.
    
    It handles JSON decoding errors and unexpected exceptions, returning appropriate error messages.
    """
    async def wrapper(action: NeuroAction, state: GameState) -> Tuple[bool, Optional[str]]:
        try:
            # Decode the JSON string contained in the action's data field
            data = json.loads(action.data)
            return await action_function(data, state)
        except json.JSONDecodeError as e:
            return False, f"Invalid JSON: {str(e)}"
        except Exception as e:
            return False, f"Unexpected error: {str(e)}"
    return wrapper

def configure_webdriver() -> webdriver.Chrome:
    """
    Configure and return a Chrome WebDriver with customized options.
    
    The function sets Chrome options for headless mode, disables sandbox/GPU usage, and 
    adds experimental options to evade automation detection.
    """
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")  # Runs Chrome in headless mode (no GUI).
    chrome_options.add_argument("--no-sandbox")      # Disables the sandbox mode for compatibility.
    chrome_options.add_argument("--disable-gpu")       # Disables GPU hardware acceleration.
    
    # Evasion parameters to make the automated browser less detectable.
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    
    # Set browser window size and mimic a common user-agent.
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    return webdriver.Chrome(options=chrome_options)

async def handle_join_phase(driver: webdriver.Chrome, roomcode: str, username: str) -> bool:
    """
    Handle the initial join phase of the game.
    
    This function waits for the room code and username input fields to become available,
    then inputs the data and clicks the join button. Returns True if successful.
    """
    try:
        # Wait for and fill in the room code input
        roomcode_box = WebDriverWait(driver, WEBDRIVER_TIMEOUT).until(
            EC.presence_of_element_located((By.ID, 'roomcode'))
        )
        roomcode_box.send_keys(roomcode)

        # Wait for and fill in the username input
        name_box = WebDriverWait(driver, WEBDRIVER_TIMEOUT).until(
            EC.presence_of_element_located((By.ID, 'username'))
        )
        name_box.send_keys(username)

        # Wait until the join button is clickable and click it
        play_button = WebDriverWait(driver, WEBDRIVER_TIMEOUT).until(
            EC.element_to_be_clickable((By.ID, 'button-join'))
        )
        play_button.click()

        return True
    except Exception as e:
        logger.error(f"Join phase failed: {str(e)}")
        return False

async def handle_answer_phase(driver: webdriver.Chrome, neuro_component: NeuroAPIComponent, state: GameState) -> bool:
    """
    Handle the question answering phase of the game.
    
    This function waits for the game to present a question, registers an action for answer
    submission via Neuro API, and submits the answer in the browser.
    Returns True if the process is successful.
    """
    try:
        state_answer_question = driver.find_element(By.ID, "state-answer-question")

        # Check if the answer page is active by inspecting its class attribute
        if "pt-page-off" not in state_answer_question.get_attribute("class"):
            await trio.sleep(ANSWER_WAIT)
            question = state_answer_question.find_element(By.ID, "question-text").text

            # Register a temporary action for answer submission over Neuro API
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
                        lambda action_data: answer_action(action_data, state),
                    ),
                ),
            )
            # Instruct the client to provide an answer using the Neuro API
            await neuro_component.send_force_action(
                f"Prompt: {question}",
                "Write a response to the given prompt.",
                ["respond"],
            )

            # Wait until the player's answer (via Neuro API) is received
            await state.played.wait()
            state.reset_played()

            # Input the submitted answer in the browser and click the submit button
            answer_box = WebDriverWait(state_answer_question, WEBDRIVER_TIMEOUT).until(
                EC.presence_of_element_located((By.ID, "quiplash-answer-input"))
            )
            answer_box.send_keys(state.response)

            submit_button = WebDriverWait(state_answer_question, WEBDRIVER_TIMEOUT).until(
                EC.element_to_be_clickable((By.ID, "quiplash-submit-answer"))
            )
            submit_button.click()

            return True
        else:
            return False
    except (NoSuchElementException, TimeoutException, ElementNotInteractableException):
        return False
    except Exception as e:
        logger.error(f"Answer handling failed: {str(e)}")
        return False

async def handle_voting_phase(driver: webdriver.Chrome, neuro_component: NeuroAPIComponent, state: GameState):
    """
    Handle the voting phase of the game.
    
    This phase allows the player to vote for the best answer. The function registers an action
    for voting via the Neuro API, waits for the vote input, and then clicks the corresponding
    vote button.
    Returns True if the voting action is handled successfully.
    """
    try:
        state_vote = driver.find_element(By.ID, "state-vote")

        # Check that the voting phase is active
        if "pt-page-off" not in state_vote.get_attribute("class"):
            await trio.sleep(PAUSE_TIME)
            vote_text = state_vote.find_element(By.ID, "vote-text").text

            # Proceed only if not in a waiting state
            if vote_text != "Wait for the other players!":
                question_text = state_vote.find_element(By.ID, "question-text").text

                # Wait until all voting buttons are present
                vote_buttons = WebDriverWait(state_vote, WEBDRIVER_TIMEOUT).until(
                    EC.presence_of_all_elements_located((By.CLASS_NAME, "quiplash2-vote-button"))
                )

                if len(vote_buttons) > 0:
                    # Prepare a list of answer options for user feedback
                    answers = [f"{i + 1}: {button.text}" for i, button in enumerate(vote_buttons)]
                    answers_str = "\n".join(answers)

                    state.vote_option_count = len(answers)
                    
                    # Register a temporary action for casting the vote via Neuro API
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
                                lambda action_data: vote_action(action_data, state),
                            ),
                        ),
                    )
                    # Force the vote action via the Neuro API with prompt information
                    await neuro_component.send_force_action(
                        "You're voting on your favorite answer to the prompt.",
                        f"Prompt: {question_text}\nAnswers:\n{answers_str}",
                        ["cast_vote"],
                    )

                    # Wait for the player's vote to be processed
                    await state.played.wait()
                    state.reset_played()

                    # Simulate clicking on the vote button corresponding to the player's choice
                    vote_buttons[state.vote].click()
                    return True
                else:
                    return False
            else:
                return False
        else:
            return False
    except (NoSuchElementException, TimeoutException, ElementNotInteractableException):
        return False
    except Exception as e:
        logger.error(f"Voting handling failed: {str(e)}")
        return False

@handle_json
async def set_name_action(data: dict, state: GameState) -> Tuple[bool, Optional[str]]:
    """
    Handle the username setting request.
    
    Validates the provided name, updates the GameState accordingly, and signals completion.
    Returns a tuple containing a success flag and a message.
    """
    if "name" not in data:
        return False, "Data must contain field 'name'."
    
    if (len(data["name"]) == 0):
        return False, "Received blank name. Must enter in a name."
    elif (len(data["name"]) <= MAX_NAME_LENGTH):
        state.username = data["name"]
        state.played.set()  # Signal that username has been set
        return True, f"{state.username = }"
    else:
        return False, f"Received {len(data['name'])} character name. Name cannot exceed {MAX_NAME_LENGTH} characters."

@handle_json  
async def answer_action(data: dict, state: GameState) -> Tuple[bool, Optional[str]]:
    """
    Handle the answer submission request.
    
    Validates the provided answer, updates GameState with the response, and signals completion.
    Returns a tuple with a success flag and a message.
    """
    if "answer" not in data:
        return False, "Data must contain field 'answer'."
    
    if (len(data["answer"]) == 0):
        return False, "Received blank answer. Must enter in an answer."
    elif (len(data["answer"]) <= MAX_ANSWER_LENGTH):
        state.response = data["answer"]
        state.played.set()  # Signal that answer has been submitted
        return True, f"{state.response = }"
    else:
        return False, f"Received {len(data['answer'])} answer. Answer cannot exceed {MAX_ANSWER_LENGTH} characters."

@handle_json
async def vote_action(data: dict, state: GameState) -> Tuple[bool, Optional[str]]:
    """
    Handle the voting request.
    
    Validates the vote number, updates the GameState with the chosen vote (adjusting for 0-based indexing),
    and signals completion.
    Returns a tuple with a success flag and a message.
    """
    if "vote" not in data:
        return False, "Data must contain field 'vote'."
    
    if type(data["vote"]) is not int:
        return False, "'vote' must be an integer."
    
    if data["vote"] <= 0 or data["vote"] > state.vote_option_count:
        return False, f"Invalid choice. Choices are from 1 to {state.vote_option_count}, inclusive."
    else:
        state.vote = data["vote"] - 1  # Convert to 0-based index
        state.played.set()  # Signal that the vote has been registered
        return True, f"{state.vote = }"

async def run() -> None:
    """
    Main asynchronous function to run the game.
    
    Establishes connection to the Neuro API; handles joining, answering, and voting phases
    by orchestrating interactions between Selenium, Trio, and the Neuro API.
    """
    websocket_url = os.environ.get(WEBSOCKET_ENV_VAR, "ws://localhost:8000")

    async with trio.open_nursery(strict_exception_groups=True) as nursery:
        # Create a manager for handling asynchronous events
        manager = ExternalRaiseManager("name", nursery)
        # Initialize Neuro API component for game interactions
        neuro_component = NeuroAPIComponent("neuro_api", "Quiplash 2")

        try:
            # Add the Neuro API component to the manager
            manager.add_component(neuro_component)

            # Register the connection handler
            neuro_component.register_handler(
                "connect",
                neuro_component.handle_connect,
            )

            # Attempt to connect to the Neuro API
            await manager.raise_event(Event("connect", websocket_url))
            await trio.sleep(WEBSOCKET_CONNECTION_WAIT_TIME)

            if neuro_component.not_connected:
                logger.error("Neuro API connection failed")
                return
            
            await neuro_component.send_startup_command()

            # Get and validate the room code from user input
            roomcode = input("Enter 4-character room code: ").strip()
            if len(roomcode) != ROOMCODE_LENGTH or not roomcode.isalpha():
                logger.error("Invalid room code")
                return

            # Initialize game state and register temporary action for username setting
            state = GameState()

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
                        lambda action_data: set_name_action(action_data, state),
                    ),
                ),
            )
            # Request the user to set their name through Neuro API
            await neuro_component.send_force_action(
                "You're starting a game of Quiplash.",
                "Choose your name.",
                ["set_name"],
            )

            # Wait for the username to be set and then reset the event for further actions
            await state.played.wait()
            state.reset_played()

            # Launch Selenium WebDriver to control the browser
            with configure_webdriver() as driver:
                driver.get(BASE_URL)  # Open the game website

                # Proceed to join phase; if failed, stop the component and exit
                if not await handle_join_phase(driver, roomcode, state.username):
                    await neuro_component.stop()
                    return

                # Main loop: alternate between answer and vote phases
                while True:
                    if await handle_answer_phase(driver, neuro_component, state):
                        await trio.sleep(PAUSE_TIME)
                        continue        
                    
                    if await handle_voting_phase(driver, neuro_component, state):
                        await trio.sleep(PAUSE_TIME)
        except (KeyboardInterrupt, trio.Cancelled):
            logger.info("Shutting down...")
            return
        finally:
            await neuro_component.stop()
            logger.info("Cleanup complete")
                

if __name__ == "__main__":
    try:
        trio.run(run)
    except ExceptionGroup as exc:
        traceback.print_exception(exc)