import sqlite3

# Function to create the database and user table if it doesn't exist
def create_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user (
            email TEXT NOT NULL,
            password TEXT NOT NULL
        )
    ''')

    conn.commit()
    conn.close()

# Function to add a new user to the database
def add_user(email, password):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO user (email, password)
        VALUES (?, ?)
    ''', (email, password))

    conn.commit()
    conn.close()

# Main script to prompt for email and password
def main():
    create_db()  # Ensure the table is created if not already present

    while True:
        # Ask user for email and password input
        email = input("Enter your email: ")
        password = input("Enter your password: ")

        # Add the user to the database
        add_user(email, password)
        print(f"User with email {email} added successfully!")

        # Ask if the user wants to add another entry
        cont = input("Do you want to add another user? (y/n): ").strip().lower()
        if cont != 'y':
            break

if __name__ == "__main__":
    main()
