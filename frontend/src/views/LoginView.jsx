export default function LoginView() {
  return (
    <div className="login-view">
      <img src="/logo.svg" width="40" height="40" alt="Weave" />
      <h1>Weave</h1>
      <button
        className="btn btn-primary"
        onClick={() => { window.location.href = '/auth/login' }}
      >
        Sign in with SSO
      </button>
    </div>
  )
}
