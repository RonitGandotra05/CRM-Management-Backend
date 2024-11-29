import sqlite3

# Function to view all users in the database
def view_users():
    # Connect to the SQLite database
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()

    # Query to select all users
    cursor.execute("SELECT * FROM user")

    # Fetch all rows from the result of the query
    users = cursor.fetchall()

    # Check if there are any users
    if users:
        print("Users in the database:")
        for user in users:
            email, password = user  # Each row is a tuple (email, password)
            print(f"Email: {email}, Password: {password}")
    else:
        print("No users found in the database.")

    # Close the connection
    conn.close()

if __name__ == "__main__":
    view_users()
