# Neuro Integration for Quiplash 2
 
This is integration to let [Neuro-sama](https://www.bloomberg.com/news/newsletters/2023-06-16/neuro-sama-an-ai-twitch-influencer-plays-minecraft-sings-karaoke-loves-art) play Quiplash 2 from the [Jackbox Party Pack 3](https://store.steampowered.com/app/434170/The_Jackbox_Party_Pack_3/) using the [Python SDK](https://github.com/CoolCat467/Neuro-API) for the [Neuro API](https://github.com/VedalAI/neuro-game-sdk). It works by using Selenium to send Neuro's responses to the [jackbox.tv](https://jackbox.tv/) website.

## Installation
> [!NOTE]
> Creating a virtual environment is recommended to avoid package version conflicts.
1. [Download](https://github.com/Kaya-Kaya/neuro-quiplash/archive/refs/tags/Latest.zip) and extract the repository.
2. Navigate into the repository directory. ```cd neuro-quiplash-Latest```
3. Create a virtual environment. (optional)
   * If you are using conda, this can be done with the command ```conda create -n neuro-quiplash python=3.12```
   * Python 3.12 is the recommended version since it was used during development, but other versions should work too.
4. Activate the virtual environment. (skip if not using a virtual environment)
   * If using conda, ```conda activate neuro-quiplash```
5. Install the requirements with ```pip install -r requirements.txt```

## Running
> [!IMPORTANT]
> Neuro should not be the first to join the lobby, since this will make her VIP and in charge of starting the game, which the integration isn't programmed to do.
1. Navigate into the repository directory. ```cd neuro-quiplash-Latest```
2. Activate the virtual environment. (skip if not using a virtual environment)
   * If using conda, ```conda activate neuro-quiplash```
3. Run the program. ```python neuro_quiplash.py```
4. Enter in the room code into the prompt.
