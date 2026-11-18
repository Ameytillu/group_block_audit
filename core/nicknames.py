"""Common English nicknames. Each line is a group of names treated as the same person.

Add your own groups to EXTRA_GROUPS below (lowercase, no punctuation).
"""
from .names import key

NICKNAME_GROUPS = [
    "robert rob bob bobby robbie bert",
    "william will bill billy willie liam",
    "richard rick rich dick ricky richie",
    "james jim jimmy jamie",
    "john jack johnny jon",
    "jonathan jon jonny nathan",
    "joseph joe joey",
    "michael mike mikey mick mickey",
    "thomas tom tommy",
    "christopher chris kit topher",
    "christina chris tina christine christy kristy",
    "daniel dan danny",
    "david dave davey",
    "matthew matt matty",
    "anthony tony",
    "andrew andy drew",
    "edward ed eddie ted teddy ned",
    "steven stephen steve stevie",
    "charles charlie chuck chas",
    "benjamin ben benny benji",
    "samuel sam sammy",
    "samantha sam sammy",
    "alexander alex al xander sandy",
    "alexandra alex alexa sandra sandy lexi",
    "nicholas nick nicky",
    "patrick pat paddy",
    "patricia pat patty tricia trish",
    "gregory greg",
    "jeffrey jeff geoffrey geoff",
    "kenneth ken kenny",
    "lawrence larry laurence",
    "leonard leo len lenny",
    "timothy tim timmy",
    "donald don donnie",
    "ronald ron ronnie",
    "raymond ray",
    "gerald gerry jerry",
    "frederick fred freddie",
    "henry hank harry",
    "harold harry hal",
    "douglas doug",
    "philip phillip phil",
    "peter pete",
    "zachary zach zack",
    "joshua josh",
    "nathaniel nate nathan nat",
    "elizabeth liz lizzy beth betty betsy eliza libby",
    "margaret maggie meg peggy marge margie",
    "katherine catherine kathryn kate katie kathy cathy kat",
    "jennifer jen jenny",
    "jessica jess jessie",
    "rebecca becky becca",
    "deborah debra deb debbie",
    "susan sue susie suzanne",
    "victoria vicky tori",
    "abigail abby",
    "kimberly kim",
    "pamela pam",
    "barbara barb barbie",
    "cynthia cindy",
    "dorothy dot dottie",
    "judith judy",
    "theresa teresa terri tess",
    "valerie val",
    "melissa missy mel",
    "melanie mel",
    "amanda mandy",
    "jacqueline jackie",
    "stephanie steph",
    "allison alison ally ali",
    "gabriel gabe",
    "gabriella gabrielle gabby",
    "anne ann annie anna",
    "mary molly mae",
]

EXTRA_GROUPS: list[str] = [
    # "venkatesh venky",
]


def _build_lookup() -> dict[str, set[str]]:
    lookup: dict[str, set[str]] = {}
    for line in NICKNAME_GROUPS + EXTRA_GROUPS:
        names = {key(n) for n in line.split()}
        for n in names:
            lookup.setdefault(n, set()).update(names)
    return lookup


_LOOKUP = _build_lookup()


def same_person_first_name(a: str, b: str) -> bool:
    """True if two first names are nicknames of each other (Bob ~ Robert)."""
    ka, kb = key(a), key(b)
    if not ka or not kb:
        return False
    return kb in _LOOKUP.get(ka, set())
