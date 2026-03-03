from dotenv import load_dotenv
import os

# Carrega o .env na raiz do projeto
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
env_path = os.path.join(BASE_DIR, ".env")
load_dotenv(env_path)

