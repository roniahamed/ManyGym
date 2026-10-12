1. Single Login Account
Each user will have one account and one set of login credentials.
One email
One password
One login session
Multiple profiles/gym accounts can be managed from the same account
2. Multiple Profiles & Gyms
A single account can have:
User Account
├── Personal Profile
├── Gym A
├── Gym B
└── Gym C
A user can create and manage multiple gym profiles without creating separate login accounts.
3. Separate Access Token for Each Profile
When a user switches to a profile or gym, the system will generate a separate access token for that specific context.
Switch → Personal Profile
        ↓
Personal Access Token
Switch → Gym A
→Gym A Access Token
Switch → Gym B
→Gym B Access Token
4. Token-Based Operations
The access token determines which profile/gym the user is currently operating on behalf of.
For example:
Gym A Token
Access Gym A members
Manage Gym A trainers
Manage Gym A settings
Gym B Token
Access Gym B People & Roles
Manage Gym B pricing plan
Manage Gym B reports 
Manage Gym B settings
A Gym A token cannot be used to perform operations on Gym B.

5. Sharing Gym Access
A gym owner can give other users access to their gym.
For example:
Gym A
├── Owner
├── Manager
└── Staff
Each user can have different permissions depending on their assigned role.
6. Role & Permission Management
Access will be controlled through roles and permissions.
For example:
Owner → Full access
Manager → Gym management
Trainer → Member and training-related access
Staff → Limited operational access
The same user can have different roles in different gyms.
Core Principle
One Login → Multiple Profiles/Gyms → Separate Access Token per Context → Context-Specific Operations & Data Access

Basic ERD
User 
Profile
Gym
Access Token
Permission
Role
Membership 
