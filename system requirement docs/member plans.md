Membership plans

This section will have three main pages.

List of Membership plans
Details of a Membership plan
Create new

Let’s talk about basic of Membership plans

In a membership plan, there are five steps:

Step 1: Basic information
Plan Name (string)
Description (string) (minimum 50 characters) (optional)
Plan status (selection) (values are: Draft / Active / Archived )

Step 2: Plan Type
Here we will discuss which type of subscription plan it will be. 
Is it a monthly plan? Or a weekly plan? Or a session wise plan, like Yoga ?

Type: Time based / Session based
Price: Float
Duration: int
Per: Day / Week / Month (For Time based type) , Session (default, for Session based)

Step 3: Payments

Joining Fee (Float)
Payment Schedule (Select field, choices are “Full Payment” / “Instalments”)
Installment schedule (object) ??????

Step 4: Access & Inclusions

Included Free Amenities ( select from the Gym’s Free amenities )
Included Paid Amenities ( Select from the Gym’s Paid amenities )

Steps 5: Terms & Conditions

Cancellation Policy (String)
Refund Policy (String)

To understand the “Plan Type” step, we are going to give an example:

type: Time based

Total Price: 69.99
Total unit: 3
Unit name: month

Live look: $69.99 for 3 Months

type: Session based

Total Price: $105.00
Total unit: 10
Unit name: session

Live look: $105.00 for 10 sessions

