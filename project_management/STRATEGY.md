# Hyde Strategy

Hyde is built in phases:

1. define the product and architecture
2. prove the core GUI + kernel model with the smallest usable shell
3. add focused tests around lifecycle and IPC
4. add user-facing features incrementally on top of the proven model
5. package and release once the minimum useful feature set is stable

The standing strategy rule is: validate architecture first, then add features through
the smallest clear extension of the existing model.
