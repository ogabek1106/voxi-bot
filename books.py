# books.py

import json
import os

BOOKS_FILE = "books_data.json"

if os.path.exists(BOOKS_FILE):
    with open(BOOKS_FILE, "r") as f:
        BOOKS = json.load(f)
else:
    BOOKS = {
        "1": {
            "file_id": "BQACAgIAAxkBAAIFo2iAoI9z_V7MDBbqv4tqS6GQawFHAALafwAC5RGYS9Jwws3o3T1MNgQ",
            "filename": "400 Must-Have Words for the TOEFL.pdf",
            "caption": "📘 *400 Must-Have Words for the TOEFL*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "2": {
            "file_id": "BQACAgIAAxkBAAIFqmiAolq8qZDLfFQCLWSU_Df06txyAAIieAACKompS9wWKnaV4VzcNgQ",
            "filename": "English Vocabulary Builder.pdf",
            "caption": "📔 *English for Everyone - English Vocabulary Builder*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "3": {
            "file_id": "BQACAgIAAxkBAAIFrGiAol2RyKBF29x2NQK3nuQfbjJfAAK5eAACKompS7kZD-2dwmYJNgQ",
            "filename": "179 IELTS Speaking Part 2 Samples.pdf",
            "caption": "📔 *179 IELTS Speaking Part 2 Samples*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "4": {
            "file_id": "BQACAgIAAxkBAAIFrmiAomAEAvg_gvmJM6ngPiyVUgSKAAKxewACCN_ZS9XyeIaFm_kvNgQ",
            "filename": "IELTS the vocabulary files.pdf",
            "caption": "📘 *IELTS the Vocabulary Files*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "5": {
            "file_id": "BQACAgIAAxkBAAIFxGiApe0xjlauq_vgcQABGAUCXpt5pQAC8XkAAq2ECUgut_tCHkHV3zYE",
            "filename": "Big Words.pdf",
            "caption": "📕 *The Big Book of Words You Should Know*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "6": {
            "file_id": "BQACAgIAAxkBAAIGMWiBGeY83--q3ByZPn4OQW34ftpjAAJWlQACLpURSMF8gX8XQvvCNgQ",
            "filename": "📘 Vocabulary Builder.pdf (Course I)",
            "caption": "📘 *Vocabulary Builder.pdf (Course I)*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "7": {
            "file_id": "BQACAgIAAxkBAAINfWiTLk7G3chZBfp2KUoGJfNGinCaAALAegACLISZSMTA2T-nz4TeNgQ",
            "filename": "📕 Vocabulary Builder.pdf (Course 2)",
            "caption": "📕 *Vocabulary Builder.pdf (Course 2)*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "8": {
            "file_id": "BQACAgIAAxkBAAIRwGicYX1BD5f1QujpsyhjTV5k6OnBAAKbiQAC5ufhSFgapiqCnLYGNgQ",
            "filename": "📗 Vocabulary Builder.pdf (Course 3)",
            "caption": "📗 *Vocabulary Builder.pdf (Course 3)*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "9": {
            "file_id": "BQACAgIAAxkBAAIR1Wicaxvc3cnpD8---RD4ySJ_U6PFAAIVigAC5ufhSERuCR3xRglyNgQ",
            "filename": "📗 The Tale of Peter Rabbit",
            "caption": "📗 *The Tale of Peter Rabbit*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "10": {
            "file_id": "BQACAgIAAxkBAAIU_mioLajZGud8x0n3YjOR0c-o2MwAA1t3AALZOkFJbDysr2yUTnA2BA",
            "filename": "📘 Glencoe Vocabulary Builder.pdf (Course 4)",
            "caption": "📘 *Glencoe Vocabulary Builder.pdf (Course 4)*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "11": {
            "file_id": "BQACAgIAAxkBAAIVtWip0HcEX7Amp5eN5AnCD4QbcLv6AAJOfgACpqdRSbpLx3JZFGz3NgQ",
            "filename": "📘 IELTS Premier with 8 Practice Tests",
            "caption": "📘 *IELTS Premier with 8 Practice Tests*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "12": {
            "file_id": "BQACAgIAAxkBAAIVvWip2wAB-1U84hCR493inA8CE6y7FQACA38AAqanUUkdVCZ5WDlVdjYE",
            "filename": "📘 English Vocabulary in Use - Upper-Intermediate.pdf",
            "caption": "📘 *English Vocabulary in Use - Upper-Intermediate.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        }
    }

    with open(BOOKS_FILE, "w") as f:
        json.dump(BOOKS, f, indent=4)
