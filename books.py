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
        },
        "13": {
            "file_id": "BQACAgIAAxkBAAIV5GiqrxiT9BA-eL3XPCLG_SO-jtZ2AAJEeQACpqdZSe6Nsj4X6EGINgQ",
            "filename": "📙Vocabulary Builder.pdf (Course 4).pdf",
            "caption": "📙 *Vocabulary Builder.pdf (Course 4).pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "14": {
            "file_id": "BQACAgIAAxkBAAIV7WiqsHQXE-LDUxwDmPXIS3w5a8BoAAJHeQACpqdZSe22A3SHkSpANgQ",
            "filename": "📙 IELTS Practice Exams.pdf",
            "caption": "📙 *IELTS Practice Exams.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "15": {
            "file_id": "BQACAgIAAxkBAAIV82iqsigKjRUfMxYhVTsAAZ8J6PXNSAACWnkAAqanWUlIWarBF-OxWTYE",
            "filename": "📘 Writing B1+ Intermediate.pdf",
            "caption": "📘 *Writing B1+ Intermediate.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "16": {
            "file_id": "BQACAgIAAxkBAAIV-WiqtFMt0yY_sBdpB72E1gABma_qaAACcHkAAqanWUlXqf03rTpVVzYE",
            "filename": "📘 Reading B1+ Intermediate.pdf",
            "caption": "📘 *Reading B1+ Intermediate.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "17": {
            "file_id": "BQACAgIAAxkBAAJPaGlKVnluK5Tk3rXoweKm0ZoCTSYlAAKdhAACogtZSpAYdtJ2_VKGNgQ",
            "filename": "📘 Speaking B1+ Intermediate.pdf",
            "caption": "📘 *Speaking B1+ Intermediate.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "18": {
            "file_id": "BQACAgIAAxkBAAJPb2lKZUJ1jaT1ryYip7Lxwwa9MZfaAAJahQACogtZStYUJMTZ35mzNgQ",
            "filename": "📘 Listening B1+ Intermediate.pdf",
            "caption": "📘 *Listening B1+ Intermediate.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "19": {
            "file_id": "BQACAgIAAxkBAAIWBmiqtyHjkAQfVwuVOYbxVWXVtClIAAKCeQACpqdZSae4EnGjQIexNgQ",
            "filename": "📔 Harry potter the complete collection.pdf",
            "caption": "📔 *Harry potter the complete collection.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "20": {
            "file_id": "BQACAgIAAxkBAAIWDGiquLJFGNcf_pwhswaOn7BTSNPrAAKQeQACpqdZSU0oFMzcFlmnNgQ",
            "filename": "📕 Daily warm-ups reading grade 5.pdf",
            "caption": "📕 *Daily warm-ups reading grade 5.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "21": {
            "file_id": "BQACAgIAAxkBAAIWEmiqud8hbPQ2NeVPIMoh8TyMc0mdAAKeeQACpqdZSQXrkAABFe45KDYE",
            "filename": "📓 Destination B1 with Answer Key.pdf",
            "caption": "📓 *Destination B1 with Answer Key.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "22": {
            "file_id": "BQACAgIAAxkBAAIWHGiqwXycalOrxu-UNBLdVf4YzrbjAAIOegACpqdZSSgg9TJEQUJXNgQ",
            "filename": "📗 Daily warm ups reading grade 4.pdf",
            "caption": "📗 *Daily warm ups reading grade 4.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "23": {
            "file_id": "BQACAgIAAxkBAAIWImiqwq-hbETab8OW-Cw7fFGhAnSpAAImegACpqdZSXDXwyvldbrjNgQ",
            "filename": "📔 NTC's Dictionary of  Easily Confused Words.pdf",
            "caption": "📔 *NTC's Dictionary of  Easily Confused Words*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "24": {
            "file_id": "BQACAgIAAxkBAAIWLmiq5VAommjB_hgVtdfYUHIqM1bXAAK6ewACpqdZSZqFjh-HDFfJNgQ",
            "filename": "📕 Daily warm ups reading grade 3.pdf",
            "caption": "📕 *Daily warm ups reading grade 3*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "25": {
            "file_id": "BQACAgIAAxkBAAIfkWjiMNxaXrGPpm8ZpD9deUXU9031AALGdQAC82IRS4FF4xl8VuQXNgQ",
            "filename": "📕Vocabulary Builder.pdf (Course 5).pdf",
            "caption": "📕 *Vocabulary Builder.pdf (Course 5).pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "26": {
            "file_id": "BQACAgIAAxkBAAIjBWjzP14AAWxWpbeT-xVuP5IkPj285QAC64IAAhTXmUuDKqgvaexnbzYE",
            "filename": "📘Vocabulary Builder.pdf (Course 6).pdf",
            "caption": "📘 *Vocabulary Builder.pdf (Course 6).pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
         "27": {
            "file_id": "BQACAgIAAxkBAAImamj7KSGgJLa_yBmji2LtwGkBSvS0AAIffgACgXvZS1PBorwiF8bVNgQ",
            "filename": "📗Vocabulary Builder.pdf (Course 7).pdf",
            "caption": "📗 *Vocabulary Builder.pdf (Course 7).pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "28": {
            "file_id": "BQACAgIAAxkBAAIoR2kDbzNAB9GYaLLWID84ZMuIkrh5AAKdggACslgYSC8gbG1TrPkbNgQ",
            "filename": "📘Essay Activator - Your Key to Writing Success.pdf",
            "caption": "📘 *Essay Activator - Your Key to Writing Success.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "29": {
            "file_id": "BQACAgIAAxkBAAIsqGkMqCFoCOhgMPuNsHCyEHTwUePvAALBhAACO1JhSICwfKZ3e-KLNgQ",
            "filename": "📙 Work on Your Phrasal Verbs.pdf",
            "caption": "📙 *Work on Your Phrasal Verbs.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "30": {
            "file_id": "BQACAgIAAxkBAAIwT2kV3e3cbB6Xn6gwh4rOQIrtJjkhAAJOigACRU-pSGtuD7aIK8V6NgQ",
            "filename": "📙 Essential Grammar in Use.pdf",
            "caption": "📙 *Essential Grammar in Use.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "31": {
            "file_id": "BQACAgIAAxkBAAI2bmkfBrRAp_kBQs5whEbq5ggzAAGQigACLIwAAnRC-Ei8KeDRKX7mfjYE",
            "filename": "📘 English Grammar in Use.pdf",
            "caption": "📘 *English Grammar in Use 4th edition.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "32": {
            "file_id": "BQACAgIAAxkBAAJHPGkxn2z0vs3ETpCxHROEVMd1rps4AAKNkwACFNSRSSdrtOi3a2P5NgQ",
            "filename": "📗 Grammarway 1.pdf",
            "caption": "📗 *Grammarway 1.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "33": {
            "file_id": "BQACAgIAAxkBAAJJKmk6pBDiWJ-Jtg4mWS0vwQAB2k5ryAACTokAAjkT2Uliu0zzu6MW1jYE",
            "filename": "📙 Grammarway 2.pdf",
            "caption": "📙 *Grammarway 2.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "34": {
            "file_id": "BQACAgIAAxkBAAJMmGlCxcJToxZoPwhRw_LaY8_NhhfwAAIEjAACCpwZSuQCKuF71UMCNgQ",
            "filename": "📕 Grammarway 3.pdf",
            "caption": "📕 *Grammarway 3.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "35": {
            "file_id": "BQACAgIAAxkBAAJPdmlKaLu7Ib_xqRpH7lkcI_0nJmV6AAKAhQACogtZSldXro7OWd-CNgQ",
            "filename": "📘 Oxford Dictionary of Idioms.pdf",
            "caption": "📘 *Oxford Dictionary of Idioms.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "36": {
            "file_id": "BQACAgIAAxkBAAJPfWlKak8TB9O7GcNDxzQlm2myqhNTAAKMhQACogtZSrIZNmXVQd4eNgQ",
            "filename": "📘Grammar Practice Pre-Intermediate Students.pdf",
            "caption": "📘 *Grammar Practice Pre-Intermediate Students.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "37": {
            "file_id": "BQACAgIAAxkBAAJPhWlKa5SxBE0yqCS4QlFt9NxKOgihAAKahQACogtZSrzrO19Alnu9NgQ",
            "filename": "📓 Daily warm ups reading grade 2.pdf",
            "caption": "📓 *Daily warm ups reading grade 2.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "38": {
            "file_id": "BQACAgIAAxkBAAJPjGlKbVh479aoflDirJVpCpUBuDDkAALBhQACogtZSrc7MTwHtvjCNgQ",
            "filename": "📕 Daily warm ups reading grade 1.pdf",
            "caption": "📕 *Daily warm ups reading grade 1.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        },
        "39": {
            "file_id": "BQACAgIAAxkBAAJWfWlNk6jXa3uRpz8xg6FNylrB4_-3AAIengAC0VtwSg-R1Kmbp_SdNgQ",
            "filename": "📕 Grammarway 4.pdf",
            "caption": "📕 *Grammarway 4*.pdf*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
        }
    }

    with open(BOOKS_FILE, "w") as f:
        json.dump(BOOKS, f, indent=4)
