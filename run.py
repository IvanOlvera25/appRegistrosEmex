# run.py (en la raíz del proyecto, junto a la carpeta "emex")
from emex import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
