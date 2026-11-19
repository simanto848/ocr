"""Deterministic realistic content generators (bn/en). No random strings."""
from __future__ import annotations
import random, datetime

BN_FIRST = ["রহিম", "করিম", "আব্দুল", "মোহাম্মদ", "ফাতেমা", "আয়েশা", "সুমন", "রina".replace("ina","িনা"),
            "সাকিব", "তানভীর", "নুসরাত", "শারমিন", "হাসান", "ইমরান", "পলাশ", "কামাল"]
BN_LAST = ["উদ্দিন", "আহমেদ", "চৌধুরী", "খান", "রহমান", "হোসেন", "সরকার", "মিয়া", "আলম", "কবির"]
EN_FIRST = ["Abdul", "Md.", "Fatema", "Suman", "Sakib", "Nusrat", "Hasan", "Imran", "Kamal", "Shila"]
EN_LAST = ["Karim", "Ahmed", "Chowdhury", "Khan", "Rahman", "Hossain", "Sarkar", "Alam", "Kabir"]
BN_DISTRICTS = ["ঢাকা", "চট্টগ্রাম", "রাজশাহী", "খুলনা", "বরিশাল", "সিলেট", "রংপুর", "ময়মনসিংহ"]
EN_DISTRICTS = ["Dhaka", "Chattogram", "Rajshahi", "Khulna", "Barishal", "Sylhet", "Rangpur"]
BN_ORGS = ["বাংলাদেশ সরকার", "ঢাকা বিশ্ববিদ্যালয়", "জাতীয় পরিচয়পত্র কর্তৃপক্ষ",
           "সোনালী ব্যাংক লিমিটেড", "বাংলাদেশ রেলওয়ে", "ঢাকা পৌরসভা"]
EN_ORGS = ["Sonali Bank Ltd.", "Bangladesh Railway", "Dhaka Municipality", "City Corporation"]
BN_PRODUCTS = ["চাল (৫ কেজি)", "ডাল (২ কেজি)", "তেল (১ লিটার)", "চিনি (১ কেজি)", "লবণ (৫০০ গ্রাম)"]
EN_PRODUCTS = ["Rice (5kg)", "Lentils (2kg)", "Oil (1L)", "Sugar (1kg)", "Salt (500g)"]

class ContentGen:
    def __init__(self, seed=42):
        self.rng = random.Random(seed)

    def person(self, lang="bn"):
        r = self.rng
        if lang == "bn":
            return f"{r.choice(BN_FIRST)} {r.choice(BN_LAST)}"
        if lang == "en":
            return f"{r.choice(EN_FIRST)} {r.choice(EN_LAST)}"
        return f"{r.choice(BN_FIRST)} {r.choice(EN_LAST)}"  # mixed

    def address(self, lang="bn"):
        r = self.rng
        if lang == "bn":
            return f"বাসা {r.randint(1,99)}, রোড {r.randint(1,20)}, {r.choice(BN_DISTRICTS)}-{r.randint(1000,9999)}"
        if lang == "en":
            return f"House {r.randint(1,99)}, Road {r.randint(1,20)}, {r.choice(EN_DISTRICTS)}-{r.randint(1000,9999)}"
        return f"বাসা {r.randint(1,99)}, Road {r.randint(1,20)}, {r.choice(EN_DISTRICTS)}"

    def phone(self):
        r = self.rng
        return f"01{r.choice(['3','5','7','8','9'])}-{r.randint(10000000,99999999):08d}"

    def date(self, lang="bn"):
        y = self.rng.randint(1990, 2026); m = self.rng.randint(1, 12); d = self.rng.randint(1, 28)
        if lang == "bn":
            bn_digits = str.translate(f"{d:02d}/{m:02d}/{y}", str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))
            return bn_digits
        return f"{d:02d}/{m:02d}/{y}"

    def invoice_no(self):
        return f"INV-{self.rng.randint(2024,2026)}-{self.rng.randint(10000,99999)}"

    def currency(self, lang="bn"):
        v = round(self.rng.uniform(50, 50000), 2)
        if lang == "bn":
            return f"৳{v:,.2f}"
        return f"Tk {v:,.2f}"

    def nid(self):
        return "".join(str(self.rng.randint(0, 9)) for _ in range(10))

    def paragraph(self, lang="bn", sentences=3):
        bn_pool = [
            "এই মর্মে প্রত্যয়ন করা যাইতেছে যে আবেদনকারী একজন বাংলাদেশের নাগরিক।",
            "সংশ্লিষ্ট কর্তৃপক্ষের নিকট যথাযথ ব্যবস্থা গ্রহণের জন্য অনুরোধ করা হইল।",
            "উল্লিখিত তথ্যাদি সঠিক বলিয়া বিবেচিত হইয়াছে এবং রেকর্ডভুক্ত করা হইয়াছে।",
            "আগামী ত্রিশ দিনের মধ্যে প্রয়োজনীয় ফি পরিশোধ করিতে হইবে।",
            "কোনো ভুল তথ্য প্রদান করিলে আইনানুগ ব্যবস্থা গ্রহণ করা হইবে।",
            "অফিস আদেশক্রমে সংশ্লিষ্ট সকলকে অবহিত করা যাইতেছে।",
            "নির্ধারিত সময়ের মধ্যে দরখাস্ত জমা দিতে ব্যর্থ হইলে আবেদন বাতিল হইবে।",
            "পরীক্ষার ফলাফল যথাসময়ে নোটিশ বোর্ডে প্রকাশ করা হইবে।",
            "বেতন ভাতাদি সরকারি নিয়মানুযায়ী প্রদান করা হইবে।",
            "ছুটির আবেদন যথাযথ কর্তৃপক্ষের মাধ্যমে দাখিল করিতে হইবে।",
            "প্রশিক্ষণ শেষে মূল্যায়ন পরীক্ষায় অংশগ্রহণ বাধ্যতামূলক।",
            "দাপ্তরিক কাজে অবহেলার কারণে শোকজ নোটিশ জারি করা হইল।",
            "বরাদ্দকৃত বাজেট থেকে ব্যয় নির্বাহ করিতে হইবে।",
            "সভার কার্যবিবরণী পরবর্তী সভায় অনুমোদনের জন্য উপস্থাপন করা হইবে।",
            "অভিযোগ প্রাপ্তির সাত কর্মদিবসের মধ্যে তদন্ত প্রতিবেদন দাখিল করিতে হইবে।",
            "সনদপত্রের মূলকপি যাচাই সাপেক্ষে নিয়োগ চূড়ান্ত করা হইবে।",
            "অফিস সময় সকাল নয়টা হইতে বিকাল পাঁচটা পর্যন্ত নির্ধারিত।",
            "জরুরি প্রয়োজনে নিয়ন্ত্রণ কক্ষে যোগাযোগ করার জন্য অনুরোধ করা হইল।",
            "বার্ষিক কর্মসম্পাদন চুক্তি যথাসময়ে স্বাক্ষর করিতে হইবে।",
            "তথ্য অধিকার আইন অনুযায়ী নির্ধারিত ফরমে আবেদন করিতে হইবে।"]
        en_pool = [
            "This is to certify that the applicant is a citizen of Bangladesh.",
            "The concerned authority is requested to take necessary action.",
            "Payment must be completed within thirty days of issuance.",
            "Any false information will result in legal action.",
            "All concerned are hereby informed by order of the office.",
            "Applications submitted after the deadline shall stand rejected.",
            "Results will be published on the notice board in due time.",
            "Allowances shall be paid in accordance with government rules.",
            "Leave applications must be submitted through proper channels.",
            "Attendance in the evaluation test after training is mandatory.",
            "A show-cause notice is hereby issued for negligence of duty.",
            "Expenditure must be met from the allocated budget.",
            "Minutes of the meeting shall be placed for approval in the next meeting.",
            "The inquiry report must be submitted within seven working days.",
            "Appointment will be finalized subject to verification of original certificates.",
            "Office hours are fixed from nine in the morning to five in the afternoon."]
        pool = bn_pool if lang == "bn" else en_pool if lang == "en" else bn_pool + en_pool
        return " ".join(self.rng.choice(pool) for _ in range(sentences))

    def table_rows(self, lang="bn", n=5, cols=("item", "qty", "price")):
        rows = []
        for _ in range(n):
            r = {}
            if "item" in cols:
                r["item"] = self.rng.choice(BN_PRODUCTS) if lang != "en" else self.rng.choice(EN_PRODUCTS)
            if "qty" in cols:
                r["qty"] = str(self.rng.randint(1, 20))
            if "price" in cols:
                r["price"] = self.currency(lang)
            rows.append(r)
        return rows
