use anchor_lang::prelude::*;

#[account]
pub struct Data {
    pub is_initialized: bool,
    pub value: u64,
}

impl Data {
    /// Refuses to run on an account that is already live.
    ///
    /// This is the guard the `init_if_needed` in `instructions/initialize.rs`
    /// relies on. It is not in that file, and a second call to the handler
    /// reaches it and fails here rather than overwriting `value`.
    pub fn init(&mut self, value: u64) -> Result<()> {
        require!(!self.is_initialized, ErrorCode::AlreadyInitialized);
        self.is_initialized = true;
        self.value = value;
        Ok(())
    }
}

#[error_code]
pub enum ErrorCode {
    #[msg("Already initialized")]
    AlreadyInitialized,
}
