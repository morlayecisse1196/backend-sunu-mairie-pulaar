from urllib.parse import quote_plus

password = input("Entre ton mot de passe Supabase : ")
encoded = quote_plus(password)
print(f"Mot de passe encodé : {encoded}")
print(f"URL complète : postgresql://postgres:{encoded}@db.ntmqnhyzpevbfosopmjy.supabase.co:5432/postgres")