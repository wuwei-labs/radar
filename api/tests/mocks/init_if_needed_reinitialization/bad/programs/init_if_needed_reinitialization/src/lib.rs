// Vulnerable, split the same way as the safe variant so the only difference is
// the guard: the state type's `init` here overwrites whatever is already there.
// A second call resets `value` on a live account.
use anchor_lang::prelude::*;

pub mod instructions;
pub mod state;

use instructions::*;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod init_if_needed_reinitialization {
    use super::*;

    pub fn initialize(ctx: Context<Initialize>, value: u64) -> Result<()> {
        instructions::initialize::handler(ctx, value)
    }
}
