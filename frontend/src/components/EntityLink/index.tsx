import { View, Text } from '@tarojs/components'
import { navigateToEntityDetail } from '../../services/navigation'
import './index.scss'

interface EntityLinkProps {
  entityId: string
  name: string
  company?: string
  entityType?: string
}

export default function EntityLink({ entityId, name, company }: EntityLinkProps) {
  return (
    <View
      className='entity-link-card'
      onClick={(e) => {
        e.stopPropagation()
        navigateToEntityDetail(entityId)
      }}
    >
      <View className='entity-link-avatar'>
        <Text className='entity-link-avatar-text'>
          {name.charAt(0)}
        </Text>
      </View>
      <View className='entity-link-info'>
        <Text className='entity-link-name'>{name}</Text>
        {company && <Text className='entity-link-company'>{company}</Text>}
      </View>
      <Text className='entity-link-arrow'>›</Text>
    </View>
  )
}
