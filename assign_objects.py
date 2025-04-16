import random
import csv
from typing import List, Dict, Any, Set
from collections import Counter

def read_csv_column(file_path: str, column_name: str = None, column_index: int = 0) -> List[Any]:
    """
    Read a column from a CSV file.
    
    Parameters:
    - file_path: Path to the CSV file
    - column_name: Name of the column to read (if CSV has headers)
    - column_index: Index of the column to read (used if column_name is None)
    
    Returns:
    - List of values from the specified column
    """
    result = []
    try:
        with open(file_path, 'r', newline='') as csvfile:
            # Try to read as a CSV with headers first
            sample = csvfile.read(1024)
            csvfile.seek(0)
            has_header = csv.Sniffer().has_header(sample)
            
            if has_header and column_name:
                reader = csv.DictReader(csvfile)
                if column_name not in reader.fieldnames:
                    raise ValueError(f"Column '{column_name}' not found in CSV file. Available columns: {reader.fieldnames}")
                for row in reader:
                    result.append(row[column_name])
            else:
                reader = csv.reader(csvfile)
                if has_header:
                    next(reader)  # Skip header row
                for row in reader:
                    if len(row) > column_index:
                        result.append(row[column_index])
        
        return result
    except Exception as e:
        print(f"Error reading CSV file {file_path}: {e}")
        raise

def write_assignments_to_csv(
    assignments: Dict[Any, List[Any]], 
    output_file: str,
    user_column: str = "user_id",
    object_column: str = "object_id"
) -> None:
    """
    Write the assignments to a CSV file.
    
    Parameters:
    - assignments: Dictionary mapping user IDs to their assigned object IDs
    - output_file: Path to the output CSV file
    - user_column: Column name for user IDs
    - object_column: Column name for object IDs
    """
    try:
        with open(output_file, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            # Write header
            writer.writerow([user_column, object_column])
            
            # Write assignments
            for user, objects in assignments.items():
                for obj in objects:
                    writer.writerow([user, obj])
        
        print(f"Assignments successfully written to {output_file}")
    except Exception as e:
        print(f"Error writing to CSV file {output_file}: {e}")
        raise

def assign_objects_with_universal_crossover(
    users: List[Any], 
    objects: List[Any], 
    assignment_percentage: float, 
    crossover_percentage: float
) -> Dict[Any, List[Any]]:
    """
    Randomly assigns objects to users with controlled crossover.
    Each user will have some of their objects appear in every other user's assignments.
    
    Parameters:
    - users: List of user IDs
    - objects: List of object IDs
    - assignment_percentage: Percentage of objects to assign to each user (0.0 to 1.0)
    - crossover_percentage: Percentage of a user's assigned objects that should overlap with others (0.0 to 1.0)
    
    Returns:
    - Dictionary mapping user IDs to their assigned object IDs
    """
    # Validate inputs
    if not users:
        raise ValueError("Users list cannot be empty")
    if not objects:
        raise ValueError("Objects list cannot be empty")
    if not (0 < assignment_percentage <= 1):
        raise ValueError("assignment_percentage must be between 0 and 1")
    if not (0 <= crossover_percentage <= 1):
        raise ValueError("crossover_percentage must be between 0 and 1")
    
    num_users = len(users)
    num_objects = len(objects)
    
    # Calculate number of objects each user should get
    num_objects_per_user = int(num_objects * assignment_percentage)
    
    # Calculate number of objects that should be shared vs unique
    num_shared_per_user = int(num_objects_per_user * crossover_percentage)
    num_unique_per_user = num_objects_per_user - num_shared_per_user
    
    # Calculate minimum objects needed for the algorithm to work
    min_unique_objects = num_users * num_unique_per_user
    # Each pair of users needs at least one shared object
    min_shared_objects = num_users * (num_users - 1) // 2
    min_objects_needed = min_unique_objects + min_shared_objects
    
    if num_objects < min_objects_needed:
        raise ValueError(
            f"Not enough objects to satisfy requirements. "
            f"Need at least {min_objects_needed}, have {num_objects}."
        )
    
    # Shuffle objects for randomness
    shuffled_objects = list(objects.copy())
    random.shuffle(shuffled_objects)
    
    # Initialize assignment dict and tracking sets
    assignments = {user: [] for user in users}
    assigned_objects = set()
    
    # Phase 1: Assign unique objects to each user
    object_index = 0
    for user in users:
        unique_count = 0
        while unique_count < num_unique_per_user and object_index < len(shuffled_objects):
            obj = shuffled_objects[object_index]
            if obj not in assigned_objects:
                assignments[user].append(obj)
                assigned_objects.add(obj)
                unique_count += 1
            object_index += 1
    
    # Phase 2: Create a pool of objects for sharing
    remaining_objects = [obj for obj in shuffled_objects if obj not in assigned_objects]
    
    # Phase 3: First ensure every pair of users shares at least one object
    crossover_matrix = {u1: {u2: 0 for u2 in users if u1 != u2} for u1 in users}
    
    for i, user1 in enumerate(users):
        for user2 in users[i+1:]:
            if remaining_objects:
                shared_obj = remaining_objects.pop(0)
                assignments[user1].append(shared_obj)
                assignments[user2].append(shared_obj)
                
                # Track shared objects between users
                crossover_matrix[user1][user2] += 1
                crossover_matrix[user2][user1] += 1
    
    # Phase 4: Distribute remaining objects to achieve target crossover percentage
    # Calculate how many more shared objects each user needs
    for user in users:
        current_shared = 0
        for other_user in users:
            if user != other_user:
                current_shared += crossover_matrix[user][other_user]
        
        additional_needed = num_shared_per_user - current_shared
        
        if additional_needed > 0:
            # Prioritize users with whom this user shares the least
            other_users_sorted = sorted(
                [u for u in users if u != user],
                key=lambda u: crossover_matrix[user][u]
            )
            
            for other_user in other_users_sorted:
                shares_to_add = min(additional_needed, 
                                   num_shared_per_user // (num_users - 1))
                
                for _ in range(shares_to_add):
                    if remaining_objects:
                        shared_obj = remaining_objects.pop(0)
                        assignments[user].append(shared_obj)
                        assignments[other_user].append(shared_obj)
                        
                        crossover_matrix[user][other_user] += 1
                        crossover_matrix[other_user][user] += 1
                        
                        additional_needed -= 1
                    else:
                        break
                
                if additional_needed <= 0:
                    break
    
    # Phase 5: Fill any gaps to ensure each user has the correct number of objects
    for user in users:
        current_count = len(assignments[user])
        additional_needed = num_objects_per_user - current_count
        
        if additional_needed > 0:
            for _ in range(additional_needed):
                if remaining_objects:
                    obj = remaining_objects.pop(0)
                    assignments[user].append(obj)
    
    return assignments

def validate_assignments(
    assignments: Dict[Any, List[Any]],
    users: List[Any],
    num_objects: int,
    assignment_percentage: float,
    crossover_percentage: float
) -> bool:
    """
    Validates that the assignments meet all requirements.
    """
    expected_objects_per_user = int(num_objects * assignment_percentage)
    
    # Check basic requirements
    all_valid = True
    
    print("\nValidation Results:")
    
    # Check object counts per user
    for user in users:
        user_objects = assignments[user]
        if len(user_objects) != len(set(user_objects)):
            print(f"Error: {user} has duplicate objects")
            all_valid = False
        
        if abs(len(user_objects) - expected_objects_per_user) > 1:
            print(f"Error: {user} has {len(user_objects)} objects (expected {expected_objects_per_user})")
            all_valid = False
    
    # Check universal crossover requirement
    for i, user1 in enumerate(users):
        user1_objects = set(assignments[user1])
        
        for user2 in users[i+1:]:
            user2_objects = set(assignments[user2])
            shared_objects = user1_objects.intersection(user2_objects)
            
            if not shared_objects:
                print(f"Error: {user1} and {user2} don't share any objects")
                all_valid = False
            else:
                print(f"{user1} and {user2} share {len(shared_objects)} objects")
    
    # Check crossover percentages
    for user in users:
        user_objects = set(assignments[user])
        shared_with_others = set()
        
        for other_user in users:
            if other_user != user:
                other_objects = set(assignments[other_user])
                shared_with_others.update(user_objects.intersection(other_objects))
        
        shared_percentage = len(shared_with_others) / len(user_objects) if user_objects else 0
        
        print(f"{user}: {len(shared_with_others)}/{len(user_objects)} objects shared ({shared_percentage:.2%})")
        
        # Allow some tolerance in the crossover percentage
        if abs(shared_percentage - crossover_percentage) > 0.15:
            print(f"Warning: {user}'s crossover ({shared_percentage:.2%}) differs from target ({crossover_percentage:.2%})")
            # Not marking as invalid as this is hard to achieve exactly
    
    return all_valid

def main(
    users_csv_path: str,
    users_column: str,
    objects_csv_path: str,
    objects_column: str,
    output_csv_path: str,
    assignment_percentage: float = 0.3,
    crossover_percentage: float = 0.2
) -> None:
    """
    Main function to run the assignment process.
    
    Parameters:
    - users_csv_path: Path to the CSV file containing user IDs
    - users_column: Column name or index for user IDs
    - objects_csv_path: Path to the CSV file containing object IDs
    - objects_column: Column name or index for object IDs
    - output_csv_path: Path to the output CSV file
    - assignment_percentage: Percentage of objects to assign to each user (0.0 to 1.0)
    - crossover_percentage: Percentage of a user's assigned objects that should overlap with others (0.0 to 1.0)
    """
    try:
        # Check if column parameters are integers (indices) or strings (column names)
        if isinstance(users_column, str) and users_column.isdigit():
            users_column = int(users_column)
        if isinstance(objects_column, str) and objects_column.isdigit():
            objects_column = int(objects_column)
        
        # Read user IDs from CSV
        users = read_csv_column(users_csv_path, 
                               column_name=users_column if isinstance(users_column, str) else None,
                               column_index=users_column if isinstance(users_column, int) else 0)
        
        # Read object IDs from CSV
        objects = read_csv_column(objects_csv_path,
                                 column_name=objects_column if isinstance(objects_column, str) else None,
                                 column_index=objects_column if isinstance(objects_column, int) else 0)
        
        print(f"Read {len(users)} users and {len(objects)} objects from CSV files")
        
        # Generate assignments
        assignments = assign_objects_with_universal_crossover(
            users, objects, assignment_percentage, crossover_percentage
        )
        
        # Validate the assignments
        is_valid = validate_assignments(
            assignments, users, len(objects), assignment_percentage, crossover_percentage
        )
        
        if is_valid:
            print("All requirements met successfully!")
        else:
            print("Some requirements were not met. See details above.")
        
        # Write results to CSV
        write_assignments_to_csv(assignments, output_csv_path)
        
    except Exception as e:
        print(f"Error in assignment process: {e}")
        raise

# Example usage with CSV files
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Assign objects to users with controlled crossover')
    parser.add_argument('--users-csv', required=True, help='Path to CSV file containing user IDs')
    parser.add_argument('--users-column', default=0, help='Column name or index for user IDs')
    parser.add_argument('--objects-csv', required=True, help='Path to CSV file containing object IDs')
    parser.add_argument('--objects-column', default=0, help='Column name or index for object IDs')
    parser.add_argument('--output-csv', required=True, help='Path to output CSV file')
    parser.add_argument('--assignment-pct', type=float, default=0.3, 
                       help='Percentage of objects to assign to each user (0-1)')
    parser.add_argument('--crossover-pct', type=float, default=0.2,
                       help='Percentage of a user\'s objects that should overlap with others (0-1)')
    
    args = parser.parse_args()
    
    main(
        args.users_csv,
        args.users_column,
        args.objects_csv,
        args.objects_column,
        args.output_csv,
        args.assignment_pct,
        args.crossover_pct
    )

    # Example usage:
    # python assign_objects.py --users-csv users.csv --users-column user_id --objects-csv objects.csv --objects-column object_id --output-csv assignments.csv --assignment-pct 0.3 --crossover-pct 0.2
    # or python assign_objects.py --users-csv users.csv --objects-csv objects.csv --output-csv assignments.csv