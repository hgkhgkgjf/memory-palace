import React from 'react'
import i18n from './i18n'

const resetKeysChanged = (currentKeys = [], previousKeys = []) => {
  if (!Array.isArray(currentKeys) || !Array.isArray(previousKeys)) {
    return currentKeys !== previousKeys
  }
  if (currentKeys.length !== previousKeys.length) {
    return true
  }
  return currentKeys.some((key, index) => key !== previousKeys[index])
}

export function RootErrorFallback({ onTryAgain }) {
  const appName = i18n.t('common.appName')
  const title = i18n.t('app.errorBoundary.title')
  const message = i18n.t('app.errorBoundary.message')
  const refreshLabel = i18n.t('common.actions.refresh')
  const tryAgainLabel = i18n.t('app.errorBoundary.tryAgain')

  const handleRefresh = () => {
    if (typeof window === 'undefined') return
    window.location?.reload?.()
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 px-6 py-10">
      <section
        role="alert"
        className="w-full max-w-xl rounded-3xl border border-white/10 bg-white/95 p-8 text-slate-900 shadow-2xl"
      >
        <p className="text-sm font-semibold uppercase tracking-[0.28em] text-amber-700">
          {appName}
        </p>
        <h1 className="mt-4 text-3xl font-semibold text-slate-950">
          {title}
        </h1>
        <p className="mt-3 text-base leading-7 text-slate-600">
          {message}
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          {typeof onTryAgain === 'function' ? (
            <button
              type="button"
              onClick={onTryAgain}
              className="inline-flex items-center rounded-full bg-slate-950 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-400/60"
            >
              {tryAgainLabel}
            </button>
          ) : null}
          <button
            type="button"
            onClick={handleRefresh}
            className="inline-flex items-center rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-900 transition hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-slate-400/60"
          >
            {refreshLabel}
          </button>
        </div>
      </section>
    </main>
  )
}

export default class RootErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false }
    this.handleTryAgain = this.handleTryAgain.bind(this)
  }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  componentDidCatch(error, errorInfo) {
    console.error('RootErrorBoundary caught render error', error, errorInfo)
  }

  componentDidUpdate(prevProps) {
    if (this.state.hasError && resetKeysChanged(this.props.resetKeys, prevProps.resetKeys)) {
      this.setState({ hasError: false })
    }
  }

  handleTryAgain() {
    this.setState({ hasError: false })
  }

  render() {
    if (this.state.hasError) {
      return <RootErrorFallback onTryAgain={this.handleTryAgain} />
    }

    return this.props.children
  }
}
