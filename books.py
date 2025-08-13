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
        }
    },
        "8": {
            "file_id": "BQACAgIAAxkBAAIRwGicYX1BD5f1QujpsyhjTV5k6OnBAAKbiQAC5ufhSFgapiqCnLYGNgQ",
            "filename": "📗 Vocabulary Builder.pdf (Course 3)",
            "caption": "📗 *Vocabulary Builder.pdf (Course 3)*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        }
    }

    with open(BOOKS_FILE, "w") as f:
        json.dump(BOOKS, f, indent=4)
