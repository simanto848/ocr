"""10 document templates. Content/style decoupled: same semantics, varied fonts/layouts."""
from __future__ import annotations
import random
from ..annotations.schema import new_doc, Element
from ..content.generators import ContentGen

DOC_TYPES = ["plain", "gov_form", "invoice", "receipt", "certificate",
             "legal", "application", "article", "academic", "mixed"]

def _lbl(v): return v  # labels stay in doc language

def build(template: str, language: str, seed: int):
    rng = random.Random(seed)
    g = ContentGen(seed)
    d = new_doc(template, language, seed)
    P = d.pages[0].elements
    lang = language
    L = lambda bn, en: bn if lang == "bn" else en if lang == "en" else rng.choice([bn, en])

    if template == "plain":
        P.append(Element("heading", L("প্রতিবেদন", "Report"), font_size=32, alignment="center"))
        P.append(Element("text", L("তারিখ", "Date") + f": {g.date(lang)}", alignment="right"))
        for _ in range(rng.randint(2, 4)):
            P.append(Element("paragraph", g.paragraph(lang, rng.randint(2, 4))))
        P.append(Element("footer", L("পৃষ্ঠা ১", "Page 1"), alignment="center"))
    elif template == "gov_form":
        P.append(Element("header", L("গণপ্রজাতন্ত্রী বাংলাদেশ সরকার", "Govt. of Bangladesh"), font_size=26, alignment="center"))
        P.append(Element("heading", L("আবেদন ফরম", "Application Form"), font_size=28, alignment="center"))
        for lbl_bn, lbl_en, gen in [
                ("আবেদনকারীর নাম", "Applicant name", lambda: g.person(lang)),
                ("জন্ম তারিখ", "Date of birth", lambda: g.date(lang)),
                ("ঠিকানা", "Address", lambda: g.address(lang)),
                ("মোবাইল নম্বর", "Mobile", g.phone),
                ("জাতীয় পরিচয়পত্র", "NID", g.nid)]:
            P.append(Element("field", f"{L(lbl_bn,lbl_en)}: {gen()}", font_size=20))
        P.append(Element("checkbox", L("☐ সত্যায়িত  ☐ সংযুক্তি", "☐ Verified  ☐ Attached")))
        P.append(Element("signature", L("স্বাক্ষর: ________   তারিখ: ", "Signature: ________   Date: ") + g.date(lang)))
        P.append(Element("footer", L("সরকারি কাজে ব্যবহার্য", "For official use"), alignment="center"))
    elif template == "invoice":
        P.append(Element("header", L("সোনালী ট্রেডার্স", "Sonali Traders"), font_size=28, alignment="center"))
        P.append(Element("text", f"{L('চালান নম্বর','Invoice')}: {g.invoice_no()}    {L('তারিখ','Date')}: {g.date(lang)}"))
        P.append(Element("field", f"{L('ক্রেতা','Customer')}: {g.person(lang)}"))
        P.append(Element("field", f"{L('ঠিকানা','Address')}: {g.address(lang)}"))
        rows = g.table_rows(lang, rng.randint(3, 8))
        P.append(Element("table", "", meta={"columns": ["item", "qty", "price"], "rows": rows}))
        total = f"৳{rng.randint(500,50000):,}.00" if lang != "en" else f"Tk {rng.randint(500,50000):,}.00"
        P.append(Element("text", f"{L('সর্বমোট','Total')}: {total}", alignment="right", font_size=24))
        P.append(Element("footer", L("৩০ দিনের মধ্যে পরিশোধযোগ্য", "Payable within 30 days"), alignment="center"))
    elif template == "receipt":
        P.append(Element("heading", L("ক্যাশ মেমো", "Cash Memo"), alignment="center", font_size=28))
        P.append(Element("text", f"{L('দোকান','Shop')}: {rng.choice(['সোনালী স্টোর','Sonali Store'])}"))
        P.append(Element("text", f"{L('লেনদেন','Txn')}: {rng.randint(100000,999999)}  {g.date(lang)}"))
        for _ in range(rng.randint(2, 6)):
            P.append(Element("text", f"{rng.choice(['চাল','Rice'])} x{rng.randint(1,5)}  {g.currency(lang)}"))
        P.append(Element("text", f"{L('মোট','Total')}: {g.currency(lang)}", font_size=24, alignment="right"))
    elif template == "certificate":
        P.append(Element("header", L("ঢাকা বিশ্ববিদ্যালয়", "University of Dhaka"), font_size=26, alignment="center"))
        P.append(Element("heading", L("প্রত্যয়নপত্র", "Certificate"), font_size=36, alignment="center"))
        P.append(Element("paragraph", L("এই মর্মে প্রত্যয়ন করা যাইতেছে যে", "This is to certify that")))
        P.append(Element("heading", g.person(lang), font_size=30, alignment="center"))
        P.append(Element("paragraph", g.paragraph(lang, 2), alignment="center"))
        P.append(Element("text", f"{L('তারিখ','Date')}: {g.date(lang)}", alignment="right"))
        P.append(Element("signature", L("স্বাক্ষর ও সিল", "Signature & Seal"), alignment="right"))
        P.append(Element("stamp", L("সত্যায়িত", "ATTESTED"), alignment="center"))
    elif template == "legal":
        P.append(Element("header", L("চুক্তিপত্র", "Deed of Agreement"), font_size=26, alignment="center"))
        P.append(Element("text", f"{L('পক্ষসমূহ','Parties')}: {g.person(lang)} {L('ও','and')} {g.person(lang)}"))
        for i in range(1, rng.randint(3, 6)):
            P.append(Element("paragraph", f"{L('ধারা','Clause')} {i}: {g.paragraph(lang, 2)}"))
        P.append(Element("signature", f"{L('স্বাক্ষর','Sign')}: ________      {L('স্বাক্ষর','Sign')}: ________"))
    elif template == "application":
        P.append(Element("heading", L("আবেদনপত্র", "Application"), alignment="center", font_size=30))
        P.append(Element("text", f"{L('প্রাপক','To')}: {rng.choice(['জেলা প্রশাসক','District Commissioner'])}"))
        P.append(Element("paragraph", g.paragraph(lang, 3)))
        P.append(Element("field", f"{L('নাম','Name')}: {g.person(lang)}"))
        P.append(Element("field", f"{L('ঠিকানা','Address')}: {g.address(lang)}"))
        P.append(Element("checkbox", "☐ NID  ☐ Photo  ☐ Fee receipt"))
        P.append(Element("signature", L("বিনীত,", "Sincerely,") + f" {g.person(lang)}"))
    elif template == "article":
        P.append(Element("heading", L("বিশেষ প্রতিবেদন", "Feature Article"), alignment="center", font_size=30))
        for _ in range(rng.randint(3, 5)):
            P.append(Element("paragraph", g.paragraph("bn-en" if lang == "mixed" else lang, 3)))
        P.append(Element("footer", L("লেখক: প্রতিবেদক", "Author: Reporter"), alignment="right"))
    elif template == "academic":
        P.append(Element("header", L("জাতীয় বিশ্ববিদ্যালয়", "National University"), alignment="center", font_size=26))
        P.append(Element("text", f"{L('কোর্স','Course')}: {rng.choice(['বাংলা ১০১','Bangla 101'])}   {L('পূর্ণমান','Marks')}: 100"))
        P.append(Element("field", f"{L('শিক্ষার্থী','Student')}: {g.person(lang)}   {L('রোল','Roll')}: {rng.randint(1,200)}"))
        for i in range(1, rng.randint(3, 6)):
            P.append(Element("paragraph", f"{L('প্রশ্ন','Q')}{i}: {g.paragraph(lang, 1)}"))
    else:  # mixed
        P.append(Element("heading", "বাংলাদেশ সরকার | Government of Bangladesh", alignment="center", font_size=28))
        P.append(Element("field", f"নাম: {g.person('mixed')} | Name: {g.person('en')}"))
        P.append(Element("field", f"ঠিকানা: {g.address('mixed')}"))
        P.append(Element("text", f"Date of Birth: {g.date('en')} | জন্ম তারিখ: {g.date('bn')}"))
        P.append(Element("text", f"Mobile: {g.phone()} | মোবাইল: {g.phone()}"))
        P.append(Element("paragraph", g.paragraph("mixed", 2)))
    # constrained layout randomization
    d.meta = {"margins": rng.choice([40, 50, 60]), "line_spacing": rng.choice([1.15, 1.3, 1.5]),
              "align_jitter": rng.random() < 0.2, "columns": 1 if template != "article" else rng.choice([1, 2])}
    return d
