export default function CardSkeleton() {
  return (
    <div className="glass rounded-2xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <div className="skeleton w-16 h-5" />
        <div className="skeleton w-10 h-5" />
      </div>
      <div className="skeleton w-3/4 h-4 mb-2" />
      <div className="skeleton w-full h-3 mb-1" />
      <div className="skeleton w-2/3 h-3 mb-3" />
      <div className="skeleton w-full h-1.5" />
    </div>
  )
}
