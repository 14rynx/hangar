from peewee import *

# Initialize the database
db = SqliteDatabase('data/bot.db')


class BaseModel(Model):
    class Meta:
        database = db


class User(BaseModel):
    user_id = CharField(primary_key=True)
    requirements_file = TextField(null=True)
    update_url = TextField(null=True)


class Character(BaseModel):
    character_id = CharField(primary_key=True)
    user = ForeignKeyField(User, backref='characters')
    token = TextField()


class CorporationCharacter(BaseModel):
    """Character with access to a corporation"""
    character_id = CharField(primary_key=True)
    corporation_id = CharField()
    user = ForeignKeyField(User, backref='corporation_characters')
    token = TextField()


class Challenge(BaseModel):
    user = ForeignKeyField(User, backref='challenges')
    state = CharField()


def initialize_database():
    with db:
        db.create_tables([User, Character, CorporationCharacter, Challenge])
