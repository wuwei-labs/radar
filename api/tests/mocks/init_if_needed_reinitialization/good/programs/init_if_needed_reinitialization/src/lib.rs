// Safe, and split the way a real program splits: `init_if_needed` is declared
// in `instructions/`, and the thing that stops a second call from overwriting
// live state is a guard inside the state type's own `init`, in `state/`. The
// handler file contains no guard of its own, so a rule that only ever sees one
// file at a time has to report it.
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
