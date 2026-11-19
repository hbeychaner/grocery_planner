import re
import unicodedata
from typing import Dict, List, Optional, Tuple


class BilingualQueryService:
    """Handles bilingual English <-> Czech grocery term translation and synonym expansion."""

    # Curated dictionary of common groceries (EN -> CS with synonyms)
    DICTIONARY: Dict[str, List[str]] = {
        # Dairy & Eggs
        "milk": ["mléko", "čerstvé mléko", "trvanlivé mléko"],
        "whole milk": ["plnotučné mléko", "mléko plnotučné"],
        "semi-skimmed milk": ["polotučné mléko"],
        "skimmed milk": ["odtučněné mléko"],
        "lactose free milk": ["bezelaktózové mléko", "bez laktózy mléko"],
        "butter": ["máslo", "jihočeské máslo"],
        "eggs": ["vejce", "vajíčka", "slepičí vejce"],
        "cheese": ["sýr", "tvrdý sýr"],
        "cheddar": ["čedar", "cheddar"],
        "gouda": ["gouda"],
        "mozzarella": ["mozzarella"],
        "parmesan": ["parmazán", "parmigiano"],
        "cottage cheese": ["cottage", "cottage sýr"],
        "cream": ["smetana"],
        "sour cream": ["zakysaná smetana"],
        "heavy cream": ["smetana ke šlehání"],
        "whipped cream": ["šlehačka"],
        "yogurt": ["jogurt", "bílý jogurt"],
        "greek yogurt": ["řecký jogurt"],

        # Bakery & Grains
        "bread": ["chléb", "chleba", "pečivo"],
        "toast bread": ["toustový chléb", "toastový chléb"],
        "roll": ["rohlík", "houska"],
        "baguette": ["bageta"],
        "croissant": ["croissant"],
        "flour": ["mouka", "hladká mouka"],
        "plain flour": ["hladká mouka"],
        "coarse flour": ["hrubá mouka"],
        "sugar": ["cukr", "cukr krupice"],
        "salt": ["sůl"],
        "rice": ["rýže", "jasmínová rýže"],
        "pasta": ["těstoviny", "špagety"],
        "spaghetti": ["špagety"],
        "oats": ["ovesné vločky", "vločky"],

        # Meat & Fish
        "chicken": ["kuře", "kuřecí maso"],
        "chicken breast": ["kuřecí prsa", "kuřecí prsní řízky"],
        "chicken thighs": ["kuřecí stehna"],
        "beef": ["hovězí maso", "hovězí"],
        "minced meat": ["mleté maso"],
        "pork": ["vepřové maso", "vepřové"],
        "bacon": ["slanina", "anglická slanina"],
        "ham": ["šunka", "vepřová šunka"],
        "salmon": ["losos", "filet z lososa"],
        "tuna": ["tuňák"],

        # Produce: Fruit & Veg
        "banana": ["banány", "banán"],
        "bananas": ["banány"],
        "apple": ["jablka", "jablko"],
        "apples": ["jablka"],
        "orange": ["pomeranče", "pomeranč"],
        "lemon": ["citrony", "citron"],
        "lime": ["limetka"],
        "avocado": ["avokádo"],
        "potato": ["brambory", "brambor"],
        "potatoes": ["brambory"],
        "onion": ["cibule", "žlutá cibule"],
        "garlic": ["česnek"],
        "tomato": ["rajčata", "rajče"],
        "tomatoes": ["rajčata"],
        "cucumber": ["okurka", "hadovka okurka"],
        "carrot": ["mrkev"],
        "lettuce": ["salát", "ledový salát"],
        "pepper": ["paprika"],
        "mushrooms": ["žampiony", "houby"],

        # Beverages & Alcohol
        "water": ["voda", "neperlivá voda"],
        "sparkling water": ["perlivá voda"],
        "still water": ["neperlivá voda"],
        "mineral water": ["minerální voda", "minerálka"],
        "beer": ["pivo", "světlý ležák"],
        "pilsner": ["pilsner urquell", "plzeň"],
        "wine": ["víno", "bílé víno", "červené víno"],
        "coffee": ["káva", "zrnková káva", "mletá káva"],
        "tea": ["čaj", "černý čaj"],
        "juice": ["džus", "pomerančový džus"],
        "coke": ["coca-cola", "kola"],

        # Pantry & Cooking
        "oil": ["olej", "slunečnicový olej", "řepkový olej"],
        "olive oil": ["olivový olej", "extra panenský olivový olej"],
    }

    def __init__(self) -> None:
        # Build inverted reverse lookup (Czech -> English)
        self.reverse_dict: Dict[str, str] = {}
        for en_term, cs_variants in self.DICTIONARY.items():
            for cs in cs_variants:
                cs_norm = self._strip_accents(cs.lower())
                self.reverse_dict[cs_norm] = en_term

    def translate_to_czech(self, query: str) -> Tuple[str, List[str]]:
        """Translate input search query to primary Czech search term and alternative synonyms.
        
        Returns:
            Tuple of (primary_czech_term, list_of_synonyms)
        """
        raw = query.strip().lower()
        cleaned = re.sub(r"[^\w\s-]", "", raw)

        # 1. Direct match in dictionary
        if cleaned in self.DICTIONARY:
            variants = self.DICTIONARY[cleaned]
            return variants[0], variants[1:]

        # 2. Check if words form a compound grocery match (e.g. "fresh milk" -> "milk")
        for en_key, cs_variants in sorted(self.DICTIONARY.items(), key=lambda x: len(x[0]), reverse=True):
            if en_key in cleaned:
                return cs_variants[0], cs_variants[1:]

        # 3. Check if query is already in Czech
        cleaned_no_accents = self._strip_accents(cleaned)
        if cleaned_no_accents in self.reverse_dict:
            # Query is already recognizable Czech term
            return raw, []

        # 4. Unknown query - pass as-is (e.g. brand name like 'Nutella' or 'Coca Cola')
        return raw, []

    @staticmethod
    def _strip_accents(text: str) -> str:
        """Remove diacritics for insensitive matching."""
        nfkd = unicodedata.normalize("NFKD", text)
        return "".join(c for c in nfkd if not unicodedata.combining(c))
