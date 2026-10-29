# UC02 Overdue Fines

Synthetic process description for the local pipeline's tests. It describes no real system.

## Page 1: Accrual

A loan returned after its due date accrues a fine of 0.25 a day, counted from the
day after the due date to the return day. Days the branch is closed are not counted.

## Page 2: Cap

A single loan's fine stops at 10.00. A lost item is charged its replacement cost
instead, and the accrued fine is waived.

## Page 3: Waivers

A supervisor can waive a fine in full with a reason code. A clerk cannot waive, and
the Waive button is hidden from a clerk. Each waiver writes an audit row naming the
supervisor and the reason code.
