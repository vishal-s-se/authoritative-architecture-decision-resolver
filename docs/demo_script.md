# Architecture Board Demo Script

**Target Duration:** 3 Minutes
**Presenter:** Engineering Lead
**Audience:** Architecture Review Board

---

### Introduction & Setup
**[TIME: 0:00 - 0:30]**

**Action:** Open the web UI, showing the "Ask AI" dashboard and the "Evaluation" metrics screen.

**Script:**
> "Hello everyone. Today I'm going to demonstrate how the Authoritative Architecture Decision Resolver ensures our engineering teams only build on officially sanctioned architectures, eliminating the confusion of conflicting specs. 
> 
> As you can see on the Evaluation page, we've tested this across 100 historical queries, achieving 90%+ accuracy without hallucinatory drift. But let's look at what happens when human governance breaks down and the system encounters a real-world conflict."

---

### Step 1: Triggering a Governance Conflict
**[TIME: 0:30 - 1:15]**

**Action:** 
1. Log in as an Engineer (e.g., `engineer1`).
2. In the "Ask AI" tab, type: `What is the approved messaging architecture?`
3. Hit submit.
4. Highlight the resulting error message: *"Conflicting approval records detected. Automatic authority resolution has been suspended."*

**Script:**
> "Here, an engineer asks for the approved messaging architecture. Instead of arbitrarily guessing or returning the newest document, the system halts. 
> 
> Why? Because behind the scenes, it detected that two different architecture owners—the Platform Team and the Security Team—both independently 'Approved' competing drafts of this architecture on the same day. The system refuses to hallucinate authority; it flags it for manual review."

---

### Step 2: The Administrator Override
**[TIME: 1:15 - 2:00]**

**Action:**
1. Log out and log back in as an Administrator (`admin`).
2. Navigate to the "Admin: Resolve Conflicts" or Document Management view.
3. Show the two conflicting versions for the messaging architecture.
4. Select the Platform Team's version and click **Manual Override**, leaving a reason: *"Platform team draft supersedes Security draft pending final consolidation."*
5. Show the Audit Log page to highlight that this override action was securely logged on the cryptographic chain.

**Script:**
> "To resolve this, I'm logging in as an administrator. We can see the two conflicting versions. After discussing with the board, we decide the Platform Team's draft is the intended path forward. 
> 
> I apply a Manual Override. This isn't a silent change—as you can see in the immutable Audit Log, my action, timestamp, and justification are permanently recorded to maintain complete traceability."

---

### Step 3: Resolving the User Query
**[TIME: 2:00 - 2:45]**

**Action:**
1. Log back in as `engineer1`.
2. Ask the exact same question: `What is the approved messaging architecture?`
3. Show the system now returning a clear answer and a direct citation (e.g., *Kafka-based event streaming*).

**Script:**
> "Now, the engineer asks the exact same question again. This time, the system seamlessly routes the query strictly to the overridden, authoritative document. 
> 
> The AI generates a grounded answer based *only* on that single source of truth, complete with a direct citation. The engineer can now proceed with confidence, knowing this decision has been explicitly de-conflicted by the board."

---

### Conclusion & Q&A
**[TIME: 2:45 - 3:00]**

**Action:** Leave the final grounded answer and citation on the screen.

**Script:**
> "In just three minutes, we've gone from a dangerous governance conflict to a securely resolved, AI-grounded answer—all with a fully transparent audit trail. I'll now open the floor for any questions."
