from calculator import RecipeParser
from datetime import datetime

try:
  from config import GAME_DATA_PATH
  base_path = GAME_DATA_PATH
except ImportError:
  print("Warning: config.py not found.")
  base_path = input("Enter path to game data folder: ")
parser = RecipeParser(base_path)
parser.export_snapshot('recipes_snapshot.json', datetime.now())
print("Snapshot generated successfully!")