// Safe pattern - two boxed accounts of *different* types.
//
// `Box<Account<'info, T>>` is how Anchor structs avoid blowing the stack, and
// `Option<Box<..>>` is its optional-account form. Neither says anything about
// duplication: `pool` and `registry` are different types and cannot be
// satisfied by one account, so "Duplicate Mutable Accounts" must stay silent.
//
// It did not. The rule read the inner type T from the field's whole `.ty`
// subtree and took the first match, which for `Box<Account<'info, T>>` is the
// Box's own type argument - `Account` - rather than T. Every boxed field in a
// struct therefore keyed to the same pseudo-type and looked like a duplicate of
// every other one.
use anchor_lang::prelude::*;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod boxed_distinct {
    use super::*;

    pub fn update(ctx: Context<Update>) -> Result<()> {
        ctx.accounts.pool.v = ctx.accounts.pool.v + 1;
        ctx.accounts.registry.n = ctx.accounts.registry.n + 1;
        Ok(())
    }
}

#[derive(Accounts)]
pub struct Update<'info> {
    #[account(mut)]
    pub pool: Box<Account<'info, Pool>>,
    #[account(mut)]
    pub registry: Box<Account<'info, Registry>>,
    pub maybe_ledger: Option<Box<Account<'info, Ledger>>>,
    pub authority: Signer<'info>,
}

#[account]
pub struct Pool {
    pub v: u64,
}

#[account]
pub struct Registry {
    pub n: u64,
}

#[account]
pub struct Ledger {
    pub total: u64,
}
